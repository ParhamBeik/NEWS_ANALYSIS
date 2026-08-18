import json

import pytest

from news_intel import pipeline
from news_intel.core import dag
from news_intel.prompts import ClassificationOutput, EvaluationOutput, SummaryOutput
from news_intel.providers import FallbackProvider, OpenAICompatibleProvider, ProviderResponse, Usage
from news_intel.sources import RawArticle


class Response:
    status_code = 200

    def __init__(self, content, usage):
        self._payload = {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}], "usage": usage}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class Session:
    def post(self, *args, **kwargs):
        return Response({"category": "other", "confidence": "متوسط", "rationale": "ok"}, {"prompt_tokens": 11, "completion_tokens": 7})


def test_provider_validates_json_and_records_reported_usage():
    provider = OpenAICompatibleProvider("gapgpt", "test", "https://example.test/v1", "secret", 3, 100, session=Session(), retry_delay=0)
    response = provider.classify(RawArticle(source="test", url="https://test/1", title="خبر"))
    assert response.data.category == "other"
    assert response.usage.tokens_in == 11
    assert response.usage.tokens_out == 7


def test_provider_does_not_retry_invalid_structured_output():
    class InvalidSession:
        def __init__(self):
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return Response({"category": "invalid", "confidence": "متوسط", "rationale": "ok"}, {})

    session = InvalidSession()
    provider = OpenAICompatibleProvider("gapgpt", "test", "https://example.test/v1", "secret", 3, 100, session=session, retry_delay=0)
    with pytest.raises(dag.Permanent, match="invalid structured output"):
        provider.classify(RawArticle(source="test", url="https://test/1", title="خبر"))
    assert session.calls == 1


class MeteredProvider:
    name = "fake"
    model = "fake-v1"
    supports_structured_output = True

    def _response(self, data):
        return ProviderResponse(data, Usage(10, 5, 0.01, self.name, self.model))

    def classify(self, article, examples=()):
        return self._response(ClassificationOutput(category="security/economics", confidence="زیاد", rationale="ok"))

    def evaluate(self, article, category, examples=()):
        return self._response(EvaluationOutput(confidence_occurrence="زیاد", gold_price_impact="زیاد", security_relevance="زیاد", gold_trend="نامطمئن", rationale="ok"))

    def summarize(self, article, examples=()):
        return self._response(SummaryOutput(optimized_title=article.title, one_line=article.title))


class Failing:
    def __init__(self, exc, name="failing", model="f1"):
        self.exc, self.name, self.model = exc, name, model
        self.supports_structured_output = True

    def classify(self, article, examples=()):
        raise self.exc

    def evaluate(self, article, category, examples=()):
        raise self.exc

    def summarize(self, article, examples=()):
        raise self.exc


def test_fallback_provider_tries_the_backup_after_exhausted_retries():
    wrapped = FallbackProvider(Failing(dag.Transient("exhausted")), MeteredProvider())
    response = wrapped.classify(RawArticle(source="test", url="https://test/1", title="خبر"))
    assert response.usage.provider == "fake"


def test_fallback_provider_tries_the_backup_after_a_fatal_auth_error():
    wrapped = FallbackProvider(Failing(dag.Fatal("auth failed")), MeteredProvider())
    response = wrapped.evaluate(RawArticle(source="test", url="https://test/1", title="خبر"), "security")
    assert response.usage.provider == "fake"


def test_fallback_provider_never_falls_back_on_a_budget_error():
    """Falling back on a budget ceiling would just keep spending past it."""
    wrapped = FallbackProvider(Failing(dag.BudgetExceeded("over budget")), MeteredProvider())
    with pytest.raises(dag.BudgetExceeded):
        wrapped.classify(RawArticle(source="test", url="https://test/1", title="خبر"))


def test_fallback_provider_reraises_when_the_backup_also_fails():
    wrapped = FallbackProvider(Failing(dag.Transient("a")), Failing(dag.Permanent("b")))
    with pytest.raises(dag.Permanent, match="b"):
        wrapped.classify(RawArticle(source="test", url="https://test/1", title="خبر"))


def test_fallback_provider_tries_the_backup_after_a_permanent_error():
    """Unparseable structured output from the primary is a Permanent error, not Transient
    or Fatal - it must still trigger the fallback like the other two do."""
    wrapped = FallbackProvider(Failing(dag.Permanent("bad json")), MeteredProvider())
    response = wrapped.classify(RawArticle(source="test", url="https://test/1", title="خبر"))
    assert response.usage.provider == "fake"


def test_fallback_provider_static_identity_is_a_composite_of_both_backends():
    wrapped = FallbackProvider(Failing(dag.Transient("x")), MeteredProvider())
    assert wrapped.name == "failing+fake"
    assert wrapped.model == "f1+fake-v1"


def test_pipeline_records_the_backend_that_actually_answered_not_the_route_identity(conn):
    """A FallbackProvider's own .name/.model are a static composite for the exists-check;
    the persisted row must reflect whichever backend actually produced it."""
    wrapped = FallbackProvider(Failing(dag.Transient("down")), MeteredProvider())
    article = RawArticle(
        source="test", url="https://test/2", title="حمله موشکی به تاسیسات نفتی کشور",
        lead="جزئیات حادثه", content="متن کامل خبر",
        published_at="2026-08-16T10:00:00+03:30",
    )
    pipeline.process(conn, [article], wrapped, run_id="fallback-run")
    row = conn.execute(
        "SELECT provider, model FROM classifications WHERE article_id="
        "(SELECT id FROM articles WHERE url=?)", (article.url,)
    ).fetchone()
    assert row["provider"] == "fake" and row["model"] == "fake-v1"


def test_fallback_provider_route_reprocesses_only_once(conn):
    """`_exists()` used to key on FallbackProvider's own composite name/model (e.g.
    "failing+fake"), which never matches the actual backend recorded on a row - so a
    route with a fallback configured re-classified (and re-billed) every article on every
    run. It must match whichever of primary/fallback actually answered."""
    wrapped = FallbackProvider(Failing(dag.Transient("down")), MeteredProvider())
    article = RawArticle(
        source="test", url="https://test/3", title="حمله موشکی به تاسیسات نفتی کشور",
        lead="جزئیات حادثه", content="متن کامل خبر",
        published_at="2026-08-16T10:00:00+03:30",
    )
    pipeline.process(conn, [article], wrapped, run_id="fallback-run-1")
    pipeline.process(conn, [article], wrapped, run_id="fallback-run-2")
    count = conn.execute(
        "SELECT COUNT(*) c FROM classifications WHERE article_id="
        "(SELECT id FROM articles WHERE url=?)", (article.url,)
    ).fetchone()["c"]
    assert count == 1


def test_pipeline_persists_provider_usage_in_node_events(conn):
    # A realistic headline: the quality gate rejects stubs like "خبر" before inference,
    # which is the point of the gate, but makes it a useless fixture for metering.
    article = RawArticle(
        source="test", url="https://test/1", title="حمله موشکی به تاسیسات نفتی کشور",
        lead="جزئیات حادثه", content="متن کامل خبر",
        published_at="2026-08-16T10:00:00+03:30",
    )
    pipeline.process(conn, [article], MeteredProvider(), run_id="metered")
    events = conn.execute("SELECT tokens_in,tokens_out,cost_usd FROM node_events WHERE run_id='metered' ORDER BY id").fetchall()
    assert len(events) == 3
    assert sum(row["tokens_in"] for row in events) == 30
    assert sum(row["tokens_out"] for row in events) == 15
    assert sum(row["cost_usd"] for row in events) == 0.03
