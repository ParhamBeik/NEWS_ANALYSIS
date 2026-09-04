"""The LLM boundary.

One HTTP attempt per call. Retry, backoff and dead-lettering belong to the Celery task;
a retry loop here would nest inside that one and compound - three attempts inside three
attempts is nine requests and nine budget charges for one logical inference, with neither
layer aware of the other. That exact bug was found and fixed once already.

Every response is validated against a pydantic schema before it is returned. An answer
that does not fit the schema is `Permanent`, not `Transient`: a model that returned a
made-up level once will return it again, and retrying spends money proving that.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TypeVar

import requests
from django.conf import settings
from pydantic import BaseModel, ValidationError

from core.errors import BudgetExceeded, Fatal, Permanent, Transient

from .budget import Usage, charge, check, reserve_call

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

REQUEST_TIMEOUT = 90


@dataclass(frozen=True)
class Answer:
    """A validated model response plus what it cost."""

    data: BaseModel
    usage: Usage


@dataclass
class GapGPTProvider:
    """OpenAI-compatible chat completions against GapGPT.

    `model` is per-instance rather than global so the bake-off can hold six of these at
    once and compare them on identical inputs.
    """

    model: str = ""
    name: str = "gapgpt"
    base_url: str = ""
    api_key: str = ""
    max_output_tokens: int = 0
    # (input, output) dollars per million tokens. Used ONLY when the provider does not
    # report its own cost, which GapGPT sometimes does not. Resolved at construction so a
    # malformed price fails at startup rather than after the money is spent.
    token_prices: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        self.model = self.model or settings.GAPGPT_MODEL
        self.base_url = (self.base_url or settings.GAPGPT_BASE_URL).rstrip("/")
        self.api_key = self.api_key or settings.GAPGPT_API_KEY
        self.max_output_tokens = self.max_output_tokens or settings.NEWS_MAX_OUTPUT_TOKENS
        if self.token_prices == (0.0, 0.0):
            self.token_prices = (
                settings.GAPGPT_INPUT_USD_PER_MILLION,
                settings.GAPGPT_OUTPUT_USD_PER_MILLION,
            )
        if not self.api_key:
            raise Fatal("GAPGPT_API_KEY is not set")
        self._session = requests.Session()

    # ------------------------------------------------------------------ http plumbing

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict, run_id: str) -> dict:
        """One attempt, with both ceilings enforced around it."""
        check(run_id)
        reserve_call(run_id)
        try:
            response = self._session.post(
                f"{self.base_url}/{path}",
                headers=self._headers(),
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise Transient(f"provider request failed: {exc}") from exc

        status = response.status_code
        if status in {401, 403}:
            # Both abort the run - a bad key and an empty wallet each fail every subsequent
            # call - but they are DIFFERENT problems and must not report as one. GapGPT
            # returns 403 with "pre-consume quota failed, remaining user quota: $0.000176"
            # when the account is out of credit. Calling that "authentication failed" sends
            # you hunting for a broken API key while the real fix is topping up the account.
            detail = response.text[:300]
            if "quota" in detail.lower() or "insufficient" in detail.lower():
                raise BudgetExceeded(f"provider quota exhausted (HTTP {status}): {detail}")
            raise Fatal(f"provider authentication failed: HTTP {status}: {detail}")
        if status == 429 or status >= 500:
            raise Transient(f"retryable HTTP {status}")
        if status >= 400:
            raise Permanent(f"provider rejected request: HTTP {status} {response.text[:300]}")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise Permanent(f"provider returned non-JSON body: {exc}") from exc

    def _usage(self, body: dict) -> Usage:
        """What the call cost, from the provider's own reported figures.

        Every number here is untrusted JSON that feeds straight into the spend counter, so
        each one is checked before it gets there. A NEGATIVE cost is the case worth naming:
        `charge` does an INCRBYFLOAT, so one would drive the run total back down and hand
        the pipeline an unlimited budget - the ceiling failing open, silently, on a value
        nobody would think to look at. A non-numeric one used to raise a bare ValueError
        that escaped the three-class taxonomy entirely, so the task died with no NodeEvent
        and no dead letter to explain it.
        """
        usage = body.get("usage") or {}
        try:
            tokens_in = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
            tokens_out = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        except (TypeError, ValueError) as exc:
            raise Permanent(f"provider returned unparseable token counts: {exc}") from exc
        if tokens_in < 0 or tokens_out < 0:
            raise Permanent("provider returned invalid usage values")

        reported = usage.get("cost_usd", body.get("cost_usd"))
        if reported is None:
            per_in, per_out = self.token_prices
            cost = (tokens_in * per_in + tokens_out * per_out) / 1_000_000
        else:
            try:
                cost = float(reported)
            except (TypeError, ValueError) as exc:
                raise Permanent(f"provider reported a non-numeric cost {reported!r}") from exc
        if cost < 0:
            raise Permanent(f"provider reported a negative cost {cost!r}")
        return Usage(tokens_in, tokens_out, cost, self.name, self.model)

    # ---------------------------------------------------------------------- inference

    def complete(self, messages: list[dict[str, str]], schema: type[T], run_id: str) -> Answer:
        """One structured completion, validated and charged."""
        body = self._post(
            "chat/completions",
            {
                "model": self.model,
                "messages": messages,
                # Zero temperature: this is a measurement instrument. Two runs of the same
                # article under the same variant should differ because the PROMPT changed,
                # not because the sampler did.
                "temperature": 0,
                "max_tokens": self.max_output_tokens,
                "response_format": {"type": "json_object"},
            },
            run_id,
        )
        usage = self._usage(body)
        charge(run_id, usage)
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise Permanent(f"provider response has no message content: {exc}") from exc

        # Truncation is NOT a schema failure, and conflating them costs real time.
        #
        # The bake-off scored gemini-3.5-flash at 13.7% and gpt-5-nano at 0%, both reported
        # as "invalid structured output" - which reads as "this model cannot produce JSON".
        # The truth was that both spend most of max_tokens on internal reasoning tokens
        # before emitting anything, so the answer was cut off mid-object. One has a fix
        # (raise the ceiling), the other does not (gpt-5-nano emitted no content even at
        # 2000). An operator cannot tell those apart from a validation traceback.
        if choice.get("finish_reason") == "length" or content is None:
            reasoning = (usage.tokens_out or 0)
            raise Permanent(
                f"provider output truncated at max_tokens={self.max_output_tokens} "
                f"(finish_reason=length, {reasoning} output tokens produced, "
                f"content {'empty' if not content else 'incomplete'}). This model needs a "
                f"higher NEWS_MAX_OUTPUT_TOKENS, or spends its budget on reasoning tokens."
            )

        try:
            data = schema.model_validate_json(content)
        except (ValidationError, json.JSONDecodeError) as exc:
            # Charged but rejected, on purpose: the call really did cost money, and hiding
            # that would make the budget under-report exactly when a model is misbehaving.
            raise Permanent(f"provider returned invalid structured output: {exc}") from exc
        return Answer(data, usage)

    def embed(
        self, texts: list[str], run_id: str, model: str = ""
    ) -> tuple[list[list[float]], Usage]:
        """Embeddings for a batch of texts, in input order."""
        body = self._post(
            "embeddings",
            {"model": model or settings.GAPGPT_EMBEDDING_MODEL, "input": texts},
            run_id,
        )
        usage = self._usage(body)
        charge(run_id, usage)
        try:
            rows = sorted(body["data"], key=lambda row: row["index"])
            vectors = [row["embedding"] for row in rows]
        except (KeyError, TypeError) as exc:
            raise Permanent(f"embedding response malformed: {exc}") from exc
        if len(vectors) != len(texts):
            raise Permanent(
                f"embedding count mismatch: asked for {len(texts)}, got {len(vectors)}"
            )
        return vectors, usage


def provider_for(variant) -> GapGPTProvider:
    """Build the provider a variant is configured to use."""
    if variant.provider != "gapgpt":
        raise Fatal(
            f"unknown provider {variant.provider!r}; only 'gapgpt' is configured. "
            "Local inference needs RAM the VPS does not currently have."
        )
    return GapGPTProvider(model=variant.model)
