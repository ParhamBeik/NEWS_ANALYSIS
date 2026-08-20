"""The LLM boundary: HTTP contract, fallback semantics, and per-node routing."""

import json

import pytest

from news_intel import config, dag, providers
from news_intel.prompts import ClassificationOutput, EvaluationOutput, SummaryOutput
from news_intel.providers import (
    FallbackProvider,
    OpenAICompatibleProvider,
    ProviderResponse,
    Route,
    RuleProvider,
    Usage,
)
from news_intel.sources import RawArticle

ARTICLE = RawArticle(source="test", url="https://test/1", title="خبر")


def build(session):
    return OpenAICompatibleProvider(
        "gapgpt", "test", "https://example.test/v1", "secret", 3, 100, session=session
    )


class Response:
    def __init__(self, content, usage=None, status_code=200):
        self.status_code = status_code
        self._payload = {
            "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
            "usage": usage or {},
        }

    def json(self):
        return self._payload


class Session:
    """Records how many HTTP attempts were made, so the "no retries here" contract is
    testable - retry/backoff belongs to dag.Node, and a second loop at this layer would
    double the effective attempt count and the max_calls spend."""

    def __init__(self, response):
        self.response, self.calls = response, 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return self.response


CLASSIFICATION = {"category": "other", "confidence": "متوسط", "rationale": "ok"}


def test_provider_validates_json_and_records_reported_usage():
    session = Session(Response(CLASSIFICATION, {"prompt_tokens": 11, "completion_tokens": 7}))
    response = build(session).classify(ARTICLE)
    assert response.data.category == "other"
    assert (response.usage.tokens_in, response.usage.tokens_out) == (11, 7)


def test_invalid_structured_output_is_permanent_and_not_retried():
    session = Session(Response({**CLASSIFICATION, "category": "invalid"}))
    with pytest.raises(dag.Permanent, match="invalid structured output"):
        build(session).classify(ARTICLE)
    assert session.calls == 1


@pytest.mark.parametrize("status,expected", [
    (503, dag.Transient), (429, dag.Transient),
    (401, dag.Fatal), (403, dag.Fatal),
    (400, dag.Permanent),
])
def test_http_status_maps_onto_the_error_taxonomy(status, expected):
    session = Session(Response(CLASSIFICATION, status_code=status))
    with pytest.raises(expected):
        build(session).classify(ARTICLE)
    assert session.calls == 1, "one HTTP attempt per call; retry lives in dag.Node"


def test_cost_falls_back_to_configured_token_prices_when_unreported():
    session = Session(Response(CLASSIFICATION, {"prompt_tokens": 1_000_000, "completion_tokens": 0}))
    per_in, _ = config.provider_token_prices()
    assert build(session).classify(ARTICLE).usage.cost_usd == pytest.approx(per_in)


# -------------------------------------------------------------------------- fallback


class MeteredProvider:
    name, model, supports_structured_output = "fake", "fake-v1", True

    def _response(self, data):
        return ProviderResponse(data, Usage(10, 5, 0.01, self.name, self.model))

    def classify(self, article, examples=()):
        return self._response(ClassificationOutput(
            category="security/economics", confidence="زیاد", rationale="ok"))

    def evaluate(self, article, category, examples=()):
        return self._response(EvaluationOutput(
            confidence_occurrence="زیاد", gold_price_impact="زیاد",
            security_relevance="زیاد", gold_trend="نامطمئن", rationale="ok"))

    def summarize(self, article, examples=()):
        return self._response(SummaryOutput(optimized_title=article.title, one_line=article.title))


class Failing:
    supports_structured_output = True

    def __init__(self, exc, name="failing", model="f1"):
        self.exc, self.name, self.model = exc, name, model

    def classify(self, article, examples=()):
        raise self.exc

    def evaluate(self, article, category, examples=()):
        raise self.exc

    def summarize(self, article, examples=()):
        raise self.exc


@pytest.mark.parametrize("failure", [
    dag.Transient("exhausted"),
    dag.Fatal("auth failed"),
    # Unparseable structured output is Permanent, not Transient or Fatal - it must still
    # trigger the fallback like the other two do.
    dag.Permanent("bad json"),
])
def test_fallback_provider_tries_the_backup(failure):
    wrapped = FallbackProvider(Failing(failure), MeteredProvider())
    assert wrapped.classify(ARTICLE).usage.provider == "fake"


def test_fallback_provider_never_falls_back_on_a_budget_error():
    """Falling back on a budget ceiling would just keep spending past it."""
    wrapped = FallbackProvider(Failing(dag.BudgetExceeded("over budget")), MeteredProvider())
    with pytest.raises(dag.BudgetExceeded):
        wrapped.classify(ARTICLE)


def test_fallback_provider_reraises_when_the_backup_also_fails():
    wrapped = FallbackProvider(Failing(dag.Transient("a")), Failing(dag.Permanent("b")))
    with pytest.raises(dag.Permanent, match="b"):
        wrapped.classify(ARTICLE)


def test_fallback_provider_static_identity_is_a_composite_of_both_backends():
    wrapped = FallbackProvider(Failing(dag.Transient("x")), MeteredProvider())
    assert (wrapped.name, wrapped.model) == ("failing+fake", "f1+fake-v1")
    assert providers.provider_identities(wrapped) == [("failing", "f1"), ("fake", "fake-v1")]


# --------------------------------------------------------------------------- routing


def write(tmp_path, text):
    path = tmp_path / "routing.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_default_applies_to_every_node(tmp_path):
    routes = providers.load_routes(write(tmp_path, "default:\n  provider: ollama\n"))
    assert {node: route.provider for node, route in routes.items()} == {
        "classify": "ollama", "evaluate": "ollama", "summarize": "ollama"
    }


def test_a_node_can_override_the_default(tmp_path):
    routes = providers.load_routes(write(tmp_path, """
default:
  provider: ollama
nodes:
  evaluate:
    provider: gapgpt
    model: gemini-2.5-flash-lite
"""))
    assert routes["classify"].provider == "ollama"
    assert routes["evaluate"] == Route("evaluate", "gapgpt", "gemini-2.5-flash-lite")


def test_a_node_may_be_written_as_a_bare_provider_name(tmp_path):
    routes = providers.load_routes(
        write(tmp_path, "default:\n  provider: rule\nnodes:\n  classify: ollama\n"))
    assert routes["classify"] == Route("classify", "ollama", None)


def test_a_node_inherits_the_default_provider_when_it_only_sets_a_model(tmp_path):
    routes = providers.load_routes(write(tmp_path, """
default:
  provider: gapgpt
nodes:
  summarize:
    model: gemini-2.5-flash
"""))
    assert routes["summarize"] == Route("summarize", "gapgpt", "gemini-2.5-flash")


@pytest.mark.parametrize("document,message", [
    # Silently falling back would mean a node quietly runs on a model nobody chose.
    ("nodes:\n  classify: rule\n", "unrouted"),
    # Without this the file looks applied but the typo'd entry does nothing.
    ("default:\n  provider: rule\nnodes:\n  classifiy: ollama\n", "unknown node"),
    ("default: [unclosed\n", "not valid YAML"),
])
def test_bad_routing_config_is_a_config_error_not_a_traceback(tmp_path, document, message):
    with pytest.raises(config.ConfigError, match=message):
        providers.load_routes(write(tmp_path, document))


def test_a_missing_file_names_the_way_out(tmp_path):
    with pytest.raises(config.ConfigError, match="--provider"):
        providers.load_routes(tmp_path / "absent.yaml")


def test_an_explicit_override_ignores_the_file_entirely(tmp_path):
    routes = providers.load_routes(write(tmp_path, "default:\n  provider: gapgpt\n"), override="rule")
    assert {route.provider for route in routes.values()} == {"rule"}


def test_the_shipped_routing_file_loads():
    """It is committed config; a broken one breaks `run --provider routed` for everybody."""
    assert set(providers.load_routes(config.ROUTING_PATH)) == set(providers.NODES)


def test_a_node_can_declare_a_fallback_provider(tmp_path):
    routes = providers.load_routes(write(tmp_path, """
default:
  provider: gapgpt
nodes:
  evaluate:
    provider: gapgpt
    fallback:
      provider: ollama
      model: qwen2.5:7b
"""))
    assert routes["evaluate"].fallback == Route("evaluate", "ollama", "qwen2.5:7b")
    assert routes["classify"].fallback is None, "fallback is never inherited implicitly"


def test_a_bare_fallback_provider_name_is_accepted(tmp_path):
    routes = providers.load_routes(write(tmp_path, """
default:
  provider: gapgpt
nodes:
  classify:
    provider: gapgpt
    fallback: ollama
"""))
    assert routes["classify"].fallback == Route("classify", "ollama", None)


def test_a_fallback_block_without_its_own_provider_is_a_config_error(tmp_path):
    with pytest.raises(config.ConfigError, match="no provider"):
        providers.load_routes(write(tmp_path, """
default:
  provider: gapgpt
nodes:
  classify:
    provider: gapgpt
    fallback:
      model: qwen2.5:7b
"""))


def test_nodes_routed_identically_share_one_provider_instance():
    """The request cap and the HTTP session live on the instance. Three copies of the same
    provider would silently triple the cap meant to stop a runaway loop."""
    built = 0

    def factory(name, *, model=None):
        nonlocal built
        built += 1
        return RuleProvider(name=name, model=model or "m")

    resolved = providers.build_routes(providers.load_routes(override="rule"), factory=factory)
    assert built == 1
    assert resolved["classify"] is resolved["evaluate"] is resolved["summarize"]


def test_differently_routed_nodes_get_different_instances():
    factory = lambda name, *, model=None: RuleProvider(name=name, model=model)
    resolved = providers.build_routes({
        "classify": Route("classify", "rule", "small"),
        "evaluate": Route("evaluate", "rule", "large"),
        "summarize": Route("summarize", "rule", "small"),
    }, factory=factory)
    assert resolved["classify"] is resolved["summarize"]
    assert resolved["classify"] is not resolved["evaluate"]


def test_a_route_with_a_fallback_builds_a_fallback_provider():
    factory = lambda name, *, model=None: RuleProvider(name=name, model=model)
    wrapped = providers.build_routes({
        "classify": Route("classify", "rule", "primary", Route("classify", "rule", "backup")),
    }, factory=factory)["classify"]
    assert isinstance(wrapped, FallbackProvider)
    assert (wrapped.primary.model, wrapped.fallback.model) == ("primary", "backup")


def test_describe_reports_node_to_model():
    assert providers.describe({"classify": RuleProvider(name="rule", model="small")}) == {
        "classify": "rule:small"
    }


def test_an_unknown_provider_name_is_refused():
    with pytest.raises(config.ConfigError, match="unknown provider"):
        providers.make_provider("nonesuch")
