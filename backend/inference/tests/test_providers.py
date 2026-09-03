"""The LLM boundary: error classification, cost accounting, and the no-nested-retry rule.

Every HTTP call here is mocked. Nothing in this suite may reach a real provider - the test
settings deliberately carry a fake API key so an un-mocked call fails loudly instead of
spending money.
"""

from __future__ import annotations

import json

import pytest
import responses
from django.test import override_settings

from core.errors import BudgetExceeded, Fatal, Permanent, Transient
from inference import budget
from inference.prompts import ClassificationOutput
from inference.providers import GapGPTProvider

RUN = "test-provider-run"
URL = "https://api.gapgpt.app/v1/chat/completions"

VALID_ANSWER = {
    "category": "security",
    "confidence": "زیاد",
    "rationale": "دلیل",
    "matched_economics_keywords": [],
    "matched_security_keywords": ["حمله"],
}


@pytest.fixture(autouse=True)
def _clean():
    budget.reset(RUN)
    budget.client().delete(budget._day_key("usd"))
    yield
    budget.reset(RUN)
    budget.client().delete(budget._day_key("usd"))


def body(answer=None, usage=None) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(answer or VALID_ANSWER)}}],
        "usage": usage if usage is not None else {"prompt_tokens": 900, "completion_tokens": 120},
    }


def messages() -> list[dict[str, str]]:
    return [{"role": "system", "content": "policy"}, {"role": "user", "content": "{}"}]


@pytest.fixture
def provider() -> GapGPTProvider:
    return GapGPTProvider(model="gemini-2.5-flash-lite")


class TestErrorTaxonomy:
    @responses.activate
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failure_is_fatal_not_permanent(self, provider, status):
        """A bad key fails EVERY call. Dead-lettering per article would quarantine the
        whole corpus one row at a time; the run has to stop instead."""
        responses.add(responses.POST, URL, json={"error": "nope"}, status=status)
        with pytest.raises(Fatal):
            provider.complete(messages(), ClassificationOutput, RUN)

    @responses.activate
    def test_an_empty_wallet_is_reported_as_quota_not_as_a_bad_key(self, provider):
        """Both abort the run, but they are different problems with different fixes.

        GapGPT returns 403 with "pre-consume quota failed, remaining user quota:
        $0.000176" when the account is out of credit. Reporting that as "authentication
        failed" sends you hunting for a broken API key while the real fix is topping up
        the account - which is exactly what happened during the first bake-off.
        """
        responses.add(
            responses.POST, URL, status=403,
            json={"error": {"message": "pre-consume quota failed, remaining user quota: $0.000176"}},
        )
        with pytest.raises(BudgetExceeded, match="quota exhausted"):
            provider.complete(messages(), ClassificationOutput, RUN)

    @responses.activate
    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_rate_limits_and_server_errors_are_transient(self, provider, status):
        responses.add(responses.POST, URL, json={"error": "later"}, status=status)
        with pytest.raises(Transient):
            provider.complete(messages(), ClassificationOutput, RUN)

    @responses.activate
    @pytest.mark.parametrize("status", [400, 404, 422])
    def test_client_errors_are_permanent(self, provider, status):
        """Retrying a request the provider rejected spends money proving it is still bad."""
        responses.add(responses.POST, URL, json={"error": "bad"}, status=status)
        with pytest.raises(Permanent):
            provider.complete(messages(), ClassificationOutput, RUN)

    @responses.activate
    def test_non_json_body_is_permanent(self, provider):
        responses.add(responses.POST, URL, body="<html>gateway</html>", status=200)
        with pytest.raises(Permanent):
            provider.complete(messages(), ClassificationOutput, RUN)

    @responses.activate
    def test_schema_violation_is_permanent(self, provider):
        """A model that invented a level outside the five-value scale will invent it
        again. This is the failure that eliminates a candidate in the bake-off."""
        responses.add(responses.POST, URL, json=body({**VALID_ANSWER, "confidence": "HIGH"}))
        with pytest.raises(Permanent, match="invalid structured output"):
            provider.complete(messages(), ClassificationOutput, RUN)

    @responses.activate
    def test_missing_message_content_is_permanent(self, provider):
        responses.add(responses.POST, URL, json={"choices": [], "usage": {}})
        with pytest.raises(Permanent):
            provider.complete(messages(), ClassificationOutput, RUN)


class TestNoNestedRetry:
    @responses.activate
    def test_exactly_one_http_request_per_call(self, provider):
        """THE regression test for retry compounding.

        A retry loop inside the provider nests inside Celery's retry: three attempts inside
        three attempts is nine HTTP calls and nine budget charges for one logical
        inference, with neither layer aware of the other. Retry ownership belongs to the
        task, so this layer must attempt exactly once.
        """
        responses.add(responses.POST, URL, json={"error": "later"}, status=503)
        with pytest.raises(Transient):
            provider.complete(messages(), ClassificationOutput, RUN)
        assert len(responses.calls) == 1

    @responses.activate
    def test_a_transient_failure_still_consumes_one_request_slot(self, provider):
        """The cap counts REQUESTS, not successes. A retry storm that never succeeds is
        exactly the runaway this ceiling exists to stop."""
        responses.add(responses.POST, URL, json={"error": "later"}, status=503)
        with pytest.raises(Transient):
            provider.complete(messages(), ClassificationOutput, RUN)
        assert budget.current(RUN).run_calls == 1


class TestCostAccounting:
    @responses.activate
    def test_uses_the_providers_reported_cost_when_present(self, provider):
        responses.add(
            responses.POST, URL,
            json=body(usage={"prompt_tokens": 900, "completion_tokens": 120, "cost_usd": 0.0042}),
        )
        answer = provider.complete(messages(), ClassificationOutput, RUN)
        assert answer.usage.cost_usd == pytest.approx(0.0042)

    @responses.activate
    @override_settings(GAPGPT_INPUT_USD_PER_MILLION=0.10, GAPGPT_OUTPUT_USD_PER_MILLION=0.40)
    def test_falls_back_to_configured_prices(self):
        """GapGPT does not always report cost. Silently recording zero would make the
        budget ceiling unreachable and the /ops cost chart a flat line at zero."""
        local = GapGPTProvider(model="m")
        responses.add(responses.POST, URL, json=body())
        answer = local.complete(messages(), ClassificationOutput, RUN)
        expected = (900 * 0.10 + 120 * 0.40) / 1_000_000
        assert answer.usage.cost_usd == pytest.approx(expected)

    @responses.activate
    def test_negative_usage_is_rejected(self, provider):
        responses.add(
            responses.POST, URL, json=body(usage={"prompt_tokens": -5, "completion_tokens": 10})
        )
        with pytest.raises(Permanent, match="invalid usage"):
            provider.complete(messages(), ClassificationOutput, RUN)

    @responses.activate
    def test_a_rejected_answer_is_still_charged(self, provider):
        """The call really did cost money. Not charging it would make the budget
        under-report exactly when a model is misbehaving and burning the most."""
        responses.add(
            responses.POST, URL,
            json=body({**VALID_ANSWER, "confidence": "HIGH"},
                      usage={"prompt_tokens": 900, "completion_tokens": 120, "cost_usd": 0.005}),
        )
        with pytest.raises(Permanent):
            provider.complete(messages(), ClassificationOutput, RUN)
        assert budget.current(RUN).run_usd == pytest.approx(0.005)


class TestRequestShape:
    @responses.activate
    def test_temperature_is_zero(self, provider):
        """This is a measurement instrument. Two runs of the same article under the same
        variant must differ because the PROMPT changed, not because the sampler did."""
        responses.add(responses.POST, URL, json=body())
        provider.complete(messages(), ClassificationOutput, RUN)
        sent = json.loads(responses.calls[0].request.body)
        assert sent["temperature"] == 0
        assert sent["response_format"] == {"type": "json_object"}
        assert sent["model"] == "gemini-2.5-flash-lite"

    @responses.activate
    def test_output_tokens_are_capped(self, provider):
        responses.add(responses.POST, URL, json=body())
        provider.complete(messages(), ClassificationOutput, RUN)
        assert json.loads(responses.calls[0].request.body)["max_tokens"] > 0

    @override_settings(GAPGPT_API_KEY="")
    def test_refuses_to_construct_without_a_key(self):
        """Fails at startup, not at the first paid call. A worker that boots without a key
        looks healthy and dead-letters every article it is handed."""
        with pytest.raises(Fatal, match="GAPGPT_API_KEY"):
            GapGPTProvider(model="m")


class TestEmbeddings:
    @responses.activate
    def test_returns_vectors_in_input_order(self, provider):
        responses.add(
            responses.POST,
            "https://api.gapgpt.app/v1/embeddings",
            json={
                "data": [
                    {"index": 1, "embedding": [0.2, 0.2]},
                    {"index": 0, "embedding": [0.1, 0.1]},
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 0},
            },
        )
        vectors, _ = provider.embed(["first", "second"], RUN)
        assert vectors == [[0.1, 0.1], [0.2, 0.2]], "provider may return data out of order"

    @responses.activate
    def test_count_mismatch_is_permanent(self, provider):
        """Silently zipping a short response against the inputs would attach one article's
        vector to a different article, poisoning every later retrieval."""
        responses.add(
            responses.POST,
            "https://api.gapgpt.app/v1/embeddings",
            json={"data": [{"index": 0, "embedding": [0.1]}], "usage": {}},
        )
        with pytest.raises(Permanent, match="count mismatch"):
            provider.embed(["a", "b"], RUN)


class TestTruncationIsNotASchemaFailure:
    """Two failures that look identical in a traceback and have different fixes.

    The bake-off scored gemini-3.5-flash at 13.7% and gpt-5-nano at 0%, both reported as
    "invalid structured output" - which reads as "this model cannot produce JSON". Both
    were actually being cut off: they spend most of max_tokens on internal reasoning
    tokens before emitting anything. One is fixable by raising the ceiling; the other is
    not. A validation traceback cannot tell you which.
    """

    @responses.activate
    def test_a_truncated_response_says_so(self, provider):
        responses.add(
            responses.POST, URL,
            json={
                "choices": [{"finish_reason": "length",
                             "message": {"content": '{"category": "sec'}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 350},
            },
        )
        with pytest.raises(Permanent, match="truncated at max_tokens"):
            provider.complete(messages(), ClassificationOutput, RUN)

    @responses.activate
    def test_an_empty_content_body_is_reported_as_truncation_not_as_a_missing_field(
        self, provider
    ):
        """A reasoning model that burns the whole budget thinking returns `content: null`
        with a 200. Reporting that as "no message content" points at the wrong layer."""
        responses.add(
            responses.POST, URL,
            json={
                "choices": [{"finish_reason": "length", "message": {"content": None}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 350},
            },
        )
        with pytest.raises(Permanent, match="reasoning tokens"):
            provider.complete(messages(), ClassificationOutput, RUN)

    @responses.activate
    def test_a_genuinely_malformed_answer_is_still_a_schema_failure(self, provider):
        """The distinction only helps if it does not swallow the real case."""
        responses.add(
            responses.POST, URL,
            json={
                "choices": [{"finish_reason": "stop",
                             "message": {"content": json.dumps({**VALID_ANSWER,
                                                                "confidence": "HIGH"})}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 120},
            },
        )
        with pytest.raises(Permanent, match="invalid structured output"):
            provider.complete(messages(), ClassificationOutput, RUN)
