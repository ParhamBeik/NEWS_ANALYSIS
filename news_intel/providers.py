"""The LLM boundary, and which model answers which node.

One model for the whole pipeline is a false economy: `classify` makes a four-way choice a
small local model can usually make, while `evaluate` produces the scores that decide
whether a human gets woken up. `config/routing.yaml` therefore maps each node to a
provider, which makes migrating to local inference partial and measurable - move
`summarize` to Ollama, read /kpi, then decide about the next node.

Providers are shared by (provider, model), never rebuilt per node: the request cap and
the HTTP session live on the instance, so three copies would silently triple the cap that
is supposed to stop a runaway loop. Retry/backoff lives one layer up, in `dag.Node`.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Generic, Iterable, Mapping, Protocol, TypeVar

import requests
import yaml
from pydantic import BaseModel, ValidationError

from . import config, dag, prompts
from .prompts import ClassificationOutput, EvaluationOutput, ReviewedExample, SummaryOutput
from .sources import RawArticle

T = TypeVar("T", bound=BaseModel)

# The nodes that issue provider calls. Anything not listed here is not routable.
NODES = ("classify", "evaluate", "summarize")


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
    """Offline keyword baseline: no network, no cost. Verifies wiring before spending."""

    name: str = "rule"
    model: str = "keyword-v1"
    supports_structured_output: bool = True

    def _response(self, data: T) -> ProviderResponse[T]:
        return ProviderResponse(data, Usage(0, 0, 0.0, self.name, self.model))

    def classify(self, article: RawArticle, examples=()):
        text = f"{article.title} {article.lead} {article.content}".lower()
        security = any(word in text for word in ("جنگ", "حمله", "امنیت", "موشک", "تحریم"))
        economics = any(word in text for word in ("طلا", "دلار", "اقتصاد", "نفت", "تورم"))
        category = (
            "security/economics" if security and economics
            else "security" if security
            else "economics" if economics
            else "other"
        )
        return self._response(ClassificationOutput(
            category=category, confidence="متوسط", rationale="offline keyword baseline"
        ))

    def evaluate(self, article: RawArticle, category: str, examples=()):
        high = "زیاد"
        values: dict[str, Any] = {
            "confidence_occurrence": high, "gold_price_impact": None,
            "security_relevance": None, "gold_trend": None, "rationale": "offline baseline",
        }
        if category == "security":
            values["security_relevance"] = high
        elif category == "economics":
            values.update(gold_price_impact=high, gold_trend="نامطمئن")
        else:
            values.update(gold_price_impact=high, security_relevance=high, gold_trend="نامطمئن")
        return self._response(EvaluationOutput(**values))

    def summarize(self, article: RawArticle, examples=()):
        return self._response(SummaryOutput(
            optimized_title=article.title, one_line=article.lead or article.title
        ))


@dataclass
class OpenAICompatibleProvider:
    name: str
    model: str
    base_url: str
    api_key: str
    max_calls: int
    max_output_tokens: int
    # (input, output) dollars per million tokens, used only when the provider does not
    # report its own cost. Resolved at construction so a malformed price in .env fails at
    # startup - reading it lazily inside _call() means a typo is only discovered after a
    # request has already been paid for, or never, if the provider always reports cost.
    token_prices: tuple[float, float] = (0.0, 0.0)
    supports_structured_output: bool = True
    session: requests.Session = field(default_factory=requests.Session, repr=False)
    _calls: int = field(default=0, init=False)
    # One instance is shared across nodes and the worker pool, so the cap counter has to
    # be atomic or the cap silently under-counts.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _call(self, messages: list[dict[str, str]], schema: type[T]) -> ProviderResponse[T]:
        """One HTTP attempt. Retry/backoff and dead-lettering belong to `dag.Node`; a
        second retry loop here would double the effective attempt count - and the
        `max_calls` spend - without either layer knowing about the other."""
        with self._lock:
            if self._calls >= self.max_calls:
                raise dag.BudgetExceeded(f"provider request cap reached: {self.max_calls}")
            self._calls += 1
        try:
            response = self.session.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.model, "messages": messages, "temperature": 0,
                      "max_tokens": self.max_output_tokens,
                      "response_format": {"type": "json_object"}},
                timeout=60,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise dag.Transient(f"provider request failed: {exc}") from exc

        status = response.status_code
        if status in {401, 403}:
            raise dag.Fatal(f"provider authentication failed: HTTP {status}")
        if status == 429 or status >= 500:
            raise dag.Transient(f"retryable HTTP {status}")
        if status >= 400:
            raise dag.Permanent(f"provider rejected request: HTTP {status}")
        try:
            body = response.json()
            data = schema.model_validate_json(body["choices"][0]["message"]["content"])
        except (KeyError, json.JSONDecodeError, ValidationError) as exc:
            raise dag.Permanent(f"provider returned invalid structured output: {exc}") from exc

        usage = body.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
        tokens_out = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
        if tokens_in < 0 or tokens_out < 0:
            raise dag.Permanent("provider returned invalid usage values")
        reported = usage.get("cost_usd", body.get("cost_usd"))
        if reported is None:
            per_in, per_out = self.token_prices
            reported = (tokens_in * per_in + tokens_out * per_out) / 1_000_000
        return ProviderResponse(
            data, Usage(tokens_in, tokens_out, float(reported), self.name, self.model)
        )

    def classify(self, article: RawArticle, examples=()):
        return self._call(prompts.messages("classification", article, examples), ClassificationOutput)

    def evaluate(self, article: RawArticle, category: str, examples=()):
        return self._call(
            prompts.messages("evaluation", article, examples, category=category), EvaluationOutput
        )

    def summarize(self, article: RawArticle, examples=()):
        return self._call(prompts.messages("summary", article, examples), SummaryOutput)


@dataclass
class FallbackProvider:
    """Try `primary`; on Transient, Permanent, or a non-budget Fatal, try `fallback`.

    `dag.BudgetExceeded` always propagates instead - falling back on a budget error would
    just keep spending past the ceiling that error exists to enforce. A single Transient
    switches immediately rather than exhausting primary's own attempts: retry lives in
    `dag.Node`, which retries the primary-then-fallback pair as a unit, so node retries and
    provider retries no longer compound.

    `.name`/`.model` are a static composite so the per-node cache check stays
    deterministic; the persisted row still records whichever backend actually answered.
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

    def _try(self, method: str, *args: Any):
        try:
            return getattr(self.primary, method)(*args)
        except dag.BudgetExceeded:
            raise
        except (dag.Transient, dag.Permanent, dag.Fatal):
            return getattr(self.fallback, method)(*args)

    def classify(self, article: RawArticle, examples=()):
        return self._try("classify", article, examples)

    def evaluate(self, article: RawArticle, category: str, examples=()):
        return self._try("evaluate", article, category, examples)

    def summarize(self, article: RawArticle, examples=()):
        return self._try("summarize", article, examples)


def provider_identities(provider: Provider) -> list[tuple[str, str]]:
    """(name, model) pairs a provider's rows can be stamped with. A FallbackProvider
    answers as whichever backend served the call, never as its composite name, so
    "was this already done?" must match against both."""
    if isinstance(provider, FallbackProvider):
        return provider_identities(provider.primary) + provider_identities(provider.fallback)
    return [(provider.name, provider.model)]


# ---------------------------------------------------------------------------- factory

# One entry per hosted provider. Adding a provider is an entry here, not a new branch.
# (model env, default model, base-url env, default base url, api key, structured output)
_HOSTED = {
    "gapgpt": ("GAPGPT_MODEL", config.DEFAULT_GAPGPT_MODEL, "GAPGPT_BASE_URL",
               "https://api.gapgpt.app/v1", lambda: config.require_env("GAPGPT_API_KEY"), True),
    "ollama": ("OLLAMA_MODEL", "qwen2.5:7b", "OLLAMA_BASE_URL",
               "http://localhost:11434/v1", lambda: config.env("OLLAMA_API_KEY", "ollama"), False),
}


def make_provider(name: str, *, model: str | None = None) -> Provider:
    """Build a provider. `model` overrides the environment default."""
    if name == "rule":
        return RuleProvider()
    if name not in _HOSTED:
        raise config.ConfigError(f"unknown provider {name!r}; choose rule, gapgpt, or ollama")
    model_env, default_model, url_env, default_url, api_key, structured = _HOSTED[name]
    model = model or config.env(model_env, default_model)
    # The legacy gapgpt value was retired June 1, 2026. Keep old .env files working.
    if name == "gapgpt" and model == "gemini-2.0-flash-lite":
        model = default_model
    return OpenAICompatibleProvider(
        name=name,
        model=model,
        base_url=config.env(url_env, default_url),
        api_key=api_key(),
        max_calls=config.provider_max_calls(),
        max_output_tokens=config.provider_max_output_tokens(),
        token_prices=config.provider_token_prices(),
        supports_structured_output=structured,
    )


# ---------------------------------------------------------------------------- routing


@dataclass(frozen=True)
class Route:
    node: str
    provider: str
    # None means "that provider's configured default model", so routing.yaml does not have
    # to be re-edited every time a model name changes in .env.
    model: str | None = None
    # Tried only when the primary is unavailable - never inherited implicitly.
    fallback: "Route | None" = None


def _coerce(node: str, value: object, default: Route | None) -> Route:
    """Accept either `classify: ollama` or a `{provider:, model:, fallback:}` mapping."""
    if isinstance(value, str):
        return Route(node, value)
    if not isinstance(value, Mapping):
        raise config.ConfigError(
            f"routing: node {node!r} must be a provider name or a mapping,"
            f" got {type(value).__name__}"
        )
    name = value.get("provider") or (default.provider if default else None)
    if not name:
        raise config.ConfigError(
            f"routing: node {node!r} has no provider and no default to fall back on"
        )
    fallback = value.get("fallback")
    return Route(
        node,
        str(name),
        str(value["model"]) if value.get("model") else None,
        _coerce(node, fallback, None) if fallback is not None else None,
    )


def load_routes(path: Path | None = None, *, override: str | None = None) -> dict[str, Route]:
    """Resolve every node to a route. `override` is the `--provider X` case: an explicit
    command-line choice beats the file for every node."""
    if override:
        return {node: Route(node, override) for node in NODES}

    path = path or config.ROUTING_PATH
    if not path.exists():
        raise config.ConfigError(
            f"missing routing config: {path}. Pass --provider to choose one explicitly."
        )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise config.ConfigError(f"routing: {path} is not valid YAML: {exc}") from exc
    if not isinstance(document, Mapping):
        raise config.ConfigError(f"routing: {path} must contain a mapping")

    raw_default = document.get("default")
    default = _coerce("default", raw_default, None) if raw_default is not None else None
    nodes = document.get("nodes") or {}
    if not isinstance(nodes, Mapping):
        raise config.ConfigError("routing: `nodes` must be a mapping of node -> provider")
    if unknown := sorted(set(nodes) - set(NODES)):
        # A typo would otherwise route nothing and look like the file was ignored.
        raise config.ConfigError(f"routing: unknown node(s) {unknown}; known nodes are {list(NODES)}")

    routes = {}
    for node in NODES:
        if node in nodes:
            routes[node] = _coerce(node, nodes[node], default)
        elif default is not None:
            routes[node] = Route(node, default.provider, default.model, default.fallback)
        else:
            raise config.ConfigError(f"routing: node {node!r} is unrouted and no `default` is set")
    return routes


def build_routes(
    routes: Mapping[str, Route], *, factory: Callable[..., Provider] = make_provider
) -> dict[str, Provider]:
    """Instantiate one provider per distinct (provider, model), shared across nodes."""
    shared: dict[tuple[str, str | None], Provider] = {}

    def instance(name: str, model: str | None) -> Provider:
        if (name, model) not in shared:
            shared[(name, model)] = factory(name, model=model)
        return shared[(name, model)]

    resolved = {}
    for node, route in routes.items():
        primary = instance(route.provider, route.model)
        resolved[node] = primary if route.fallback is None else FallbackProvider(
            primary, instance(route.fallback.provider, route.fallback.model)
        )
    return resolved


def resolve(choice: str) -> dict[str, Provider]:
    """`routed` reads config/routing.yaml; anything else pins every node to one provider."""
    return build_routes(load_routes(override=None if choice == "routed" else choice))


def describe(providers: Mapping[str, Provider]) -> dict[str, str]:
    """Compact `node -> provider:model` map, for run logs and the CLI."""
    return {node: f"{p.name}:{p.model}" for node, p in providers.items()}
