"""Provider boundary with validated JSON, bounded retries, and real usage capture."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Generic, Iterable, Protocol, TypeVar

import requests
from pydantic import BaseModel, ValidationError

from .core import config, dag
from .prompts import (
    ClassificationOutput,
    EvaluationOutput,
    ReviewedExample,
    SummaryOutput,
    classification_messages,
    evaluation_messages,
    summary_messages,
)
from .sources import RawArticle

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Usage:
    tokens_in: int
    tokens_out: int
    cost_usd: float
    provider: str
    model: str


@dataclass(frozen=True)
class ProviderResponse(Generic[T]):
    data: T
    usage: Usage


class Provider(Protocol):
    name: str
    model: str
    supports_structured_output: bool

    def classify(self, article: RawArticle, examples: Iterable[ReviewedExample] = ()) -> ProviderResponse[ClassificationOutput]: ...
    def evaluate(self, article: RawArticle, category: str, examples: Iterable[ReviewedExample] = ()) -> ProviderResponse[EvaluationOutput]: ...
    def summarize(self, article: RawArticle, examples: Iterable[ReviewedExample] = ()) -> ProviderResponse[SummaryOutput]: ...


@dataclass
class RuleProvider:
    name: str = "rule"
    model: str = "keyword-v1"
    supports_structured_output: bool = True

    def _response(self, data: T) -> ProviderResponse[T]:
        return ProviderResponse(data, Usage(0, 0, 0.0, self.name, self.model))

    def classify(self, article: RawArticle, examples=()):
        text = f"{article.title} {article.lead} {article.content}".lower()
        security = any(word in text for word in ("جنگ", "حمله", "امنیت", "موشک", "تحریم"))
        economics = any(word in text for word in ("طلا", "دلار", "اقتصاد", "نفت", "تورم"))
        category = "security/economics" if security and economics else "security" if security else "economics" if economics else "other"
        return self._response(ClassificationOutput(category=category, confidence="متوسط", rationale="offline keyword baseline"))

    def evaluate(self, article: RawArticle, category: str, examples=()):
        high = "زیاد"
        values = {"confidence_occurrence": high, "gold_price_impact": None, "security_relevance": None, "gold_trend": None, "rationale": "offline baseline"}
        if category == "security":
            values["security_relevance"] = high
        elif category == "economics":
            values["gold_price_impact"] = high
            values["gold_trend"] = "نامطمئن"
        else:
            values.update(gold_price_impact=high, security_relevance=high, gold_trend="نامطمئن")
        return self._response(EvaluationOutput(**values))

    def summarize(self, article: RawArticle, examples=()):
        return self._response(SummaryOutput(optimized_title=article.title, one_line=article.lead or article.title))


@dataclass
class OpenAICompatibleProvider:
    name: str
    model: str
    base_url: str
    api_key: str
    max_calls: int
    max_output_tokens: int
    supports_structured_output: bool = True
    session: requests.Session = field(default_factory=requests.Session, repr=False)
    retry_delay: float = 1.0
    _calls: int = field(default=0, init=False)
    # One instance is shared across nodes and across the node worker pool, so the
    # counter that enforces the cap has to be atomic or the cap silently under-counts.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _reserve_call(self) -> None:
        with self._lock:
            if self._calls >= self.max_calls:
                raise dag.BudgetExceeded(f"provider request cap reached: {self.max_calls}")
            self._calls += 1

    def _call(self, messages: list[dict[str, str]], schema: type[T]) -> ProviderResponse[T]:
        prices = config.provider_token_prices()
        for attempt in range(1, 4):
            self._reserve_call()
            try:
                response = self.session.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0,
                        "max_tokens": self.max_output_tokens,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=60,
                )
                if response.status_code in {401, 403}:
                    raise dag.Fatal(f"provider authentication failed: HTTP {response.status_code}")
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"retryable HTTP {response.status_code}", response=response)
                if response.status_code >= 400:
                    raise dag.Permanent(f"provider rejected request: HTTP {response.status_code}")
                try:
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                    data = schema.model_validate_json(content)
                except (KeyError, json.JSONDecodeError, ValidationError) as exc:
                    raise dag.Permanent(f"provider returned invalid structured output: {exc}") from exc
                usage = body.get("usage") or {}
                tokens_in = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
                tokens_out = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
                if tokens_in < 0 or tokens_out < 0:
                    raise dag.Permanent("provider returned invalid usage values")
                cost = usage.get("cost_usd", body.get("cost_usd"))
                cost_usd = float(cost) if cost is not None else tokens_in * prices[0] / 1_000_000 + tokens_out * prices[1] / 1_000_000
                return ProviderResponse(data, Usage(tokens_in, tokens_out, cost_usd, self.name, self.model))
            except dag.Fatal:
                raise
            except dag.Permanent:
                raise
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                if attempt == 3:
                    raise dag.Transient(f"provider request failed after {attempt} attempts: {exc}") from exc
                time.sleep(self.retry_delay * attempt)
        raise dag.Permanent("provider retry loop fell through")

    def classify(self, article: RawArticle, examples=()):
        return self._call(classification_messages(article, examples), ClassificationOutput)

    def evaluate(self, article: RawArticle, category: str, examples=()):
        return self._call(evaluation_messages(article, category, examples), EvaluationOutput)

    def summarize(self, article: RawArticle, examples=()):
        return self._call(summary_messages(article, examples), SummaryOutput)


@dataclass
class FallbackProvider:
    """Try `primary`; on exhausted retries, a bad response, or a non-budget Fatal, try `fallback`.

    `dag.BudgetExceeded` (a `Fatal` subclass, raised by both the run's dollar ceiling and
    a provider's own request-count cap) is deliberately NOT a fallback trigger and always
    propagates immediately - falling back to a second provider on a budget error would
    just keep spending past the ceiling that error exists to enforce. Auth failures,
    exhausted-retry Transient errors, and Permanent errors (e.g. unparseable structured
    output) all mean "this provider isn't answering usefully right now", which is exactly
    what a fallback should catch.
    """

    primary: Provider
    fallback: Provider
    supports_structured_output: bool = field(init=False)
    name: str = field(init=False)
    model: str = field(init=False)

    def __post_init__(self) -> None:
        self.supports_structured_output = self.primary.supports_structured_output
        self.name = f"{self.primary.name}+{self.fallback.name}"
        self.model = f"{self.primary.model}+{self.fallback.model}"

    def _try(self, method: str, *args: Any, **kwargs: Any):
        try:
            return getattr(self.primary, method)(*args, **kwargs)
        except dag.BudgetExceeded:
            raise
        except (dag.Transient, dag.Permanent, dag.Fatal):
            return getattr(self.fallback, method)(*args, **kwargs)

    def classify(self, article: RawArticle, examples=()):
        return self._try("classify", article, examples)

    def evaluate(self, article: RawArticle, category: str, examples=()):
        return self._try("evaluate", article, category, examples)

    def summarize(self, article: RawArticle, examples=()):
        return self._try("summarize", article, examples)


def provider_identities(provider: Provider) -> list[tuple[str, str]]:
    """(name, model) pairs a provider's result rows can actually be stamped with.

    A plain provider always answers as itself. A `FallbackProvider` answers as whichever
    of primary/fallback actually served the call (see `Usage` in `_call`/`_response`),
    never as its own composite `name`/`model` - callers checking "was this already done"
    must match against both.
    """
    if isinstance(provider, FallbackProvider):
        return provider_identities(provider.primary) + provider_identities(provider.fallback)
    return [(provider.name, provider.model)]


def make_provider(name: str, *, model: str | None = None) -> Provider:
    """Build a provider. `model` overrides the environment default (see routing.py)."""
    if name == "rule":
        return RuleProvider()
    if name in {"gapgpt", "ollama"}:
        model = model or config.env(
            "GAPGPT_MODEL" if name == "gapgpt" else "OLLAMA_MODEL",
            config.DEFAULT_GAPGPT_MODEL if name == "gapgpt" else "qwen2.5:7b",
        )
        # The legacy value was retired June 1, 2026. Keep old .env files safe.
        if name == "gapgpt" and model == "gemini-2.0-flash-lite":
            model = config.DEFAULT_GAPGPT_MODEL
        return OpenAICompatibleProvider(
            name=name,
            model=model,
            base_url=config.env("GAPGPT_BASE_URL" if name == "gapgpt" else "OLLAMA_BASE_URL", "https://api.gapgpt.app/v1" if name == "gapgpt" else "http://localhost:11434/v1"),
            api_key=config.require_env("GAPGPT_API_KEY") if name == "gapgpt" else config.env("OLLAMA_API_KEY", "ollama"),
            max_calls=config.provider_max_calls(),
            max_output_tokens=config.provider_max_output_tokens(),
            supports_structured_output=name == "gapgpt",
        )
    raise config.ConfigError(f"unknown provider {name!r}; choose rule, gapgpt, or ollama")
