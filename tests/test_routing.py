import pytest

from news_intel import pipeline, routing
from news_intel.core import config
from news_intel.providers import RuleProvider
from news_intel.sources import RawArticle


def write(tmp_path, text):
    path = tmp_path / "routing.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class Recording(RuleProvider):
    """A rule provider that remembers which nodes called it."""

    def __init__(self, name, model):
        super().__init__(name=name, model=model)
        self.calls = []

    def classify(self, article, examples=()):
        self.calls.append("classify")
        return super().classify(article, examples)

    def evaluate(self, article, category, examples=()):
        self.calls.append("evaluate")
        return super().evaluate(article, category, examples)

    def summarize(self, article, examples=()):
        self.calls.append("summarize")
        return super().summarize(article, examples)


# ------------------------------------------------------------------ loading


def test_default_applies_to_every_node(tmp_path):
    routes = routing.load(write(tmp_path, "default:\n  provider: ollama\n"))
    assert {node: route.provider for node, route in routes.items()} == {
        "classify": "ollama", "evaluate": "ollama", "summarize": "ollama"
    }


def test_a_node_can_override_the_default(tmp_path):
    routes = routing.load(write(tmp_path, """
default:
  provider: ollama
nodes:
  evaluate:
    provider: gapgpt
    model: gemini-2.5-flash-lite
"""))
    assert routes["classify"].provider == "ollama"
    assert routes["evaluate"].provider == "gapgpt"
    assert routes["evaluate"].model == "gemini-2.5-flash-lite"


def test_a_node_may_be_written_as_a_bare_provider_name(tmp_path):
    routes = routing.load(write(tmp_path, "default:\n  provider: rule\nnodes:\n  classify: ollama\n"))
    assert routes["classify"] == routing.Route("classify", "ollama", None)


def test_a_node_inherits_the_default_provider_when_it_only_sets_a_model(tmp_path):
    routes = routing.load(write(tmp_path, """
default:
  provider: gapgpt
nodes:
  summarize:
    model: gemini-2.5-flash
"""))
    assert routes["summarize"] == routing.Route("summarize", "gapgpt", "gemini-2.5-flash")


def test_an_unrouted_node_without_a_default_is_a_config_error(tmp_path):
    # Silently falling back would mean a node quietly runs on a model nobody chose.
    with pytest.raises(config.ConfigError, match="unrouted"):
        routing.load(write(tmp_path, "nodes:\n  classify: rule\n"))


def test_a_misspelled_node_name_is_rejected(tmp_path):
    # Without this the file looks applied but the typo'd entry does nothing.
    with pytest.raises(config.ConfigError, match="unknown node"):
        routing.load(write(tmp_path, "default:\n  provider: rule\nnodes:\n  classifiy: ollama\n"))


def test_a_missing_file_names_the_way_out(tmp_path):
    with pytest.raises(config.ConfigError, match="--provider"):
        routing.load(tmp_path / "absent.yaml")


def test_malformed_yaml_is_a_config_error_not_a_traceback(tmp_path):
    with pytest.raises(config.ConfigError, match="not valid YAML"):
        routing.load(write(tmp_path, "default: [unclosed\n"))


def test_an_explicit_override_ignores_the_file_entirely(tmp_path):
    routes = routing.load(write(tmp_path, "default:\n  provider: gapgpt\n"), override="rule")
    assert {route.provider for route in routes.values()} == {"rule"}


def test_the_shipped_routing_file_loads():
    # It is committed config; a broken one breaks `run --provider routed` for everybody.
    assert set(routing.load(config.ROUTING_PATH)) == set(routing.NODES)


# ------------------------------------------------------------------ building


def test_nodes_routed_identically_share_one_provider_instance():
    # The request cap and the HTTP session live on the instance. Three copies of the
    # same provider would silently triple the cap meant to stop a runaway loop.
    built = 0

    def factory(name, *, model=None):
        nonlocal built
        built += 1
        return RuleProvider(name=name, model=model or "m")

    providers = routing.build(routing.load(override="rule"), factory=factory)
    assert built == 1
    assert providers["classify"] is providers["evaluate"] is providers["summarize"]


def test_differently_routed_nodes_get_different_instances():
    routes = {
        "classify": routing.Route("classify", "rule", "small"),
        "evaluate": routing.Route("evaluate", "rule", "large"),
        "summarize": routing.Route("summarize", "rule", "small"),
    }
    providers = routing.build(routes, factory=lambda name, *, model=None: RuleProvider(name=name, model=model))
    assert providers["classify"] is providers["summarize"]
    assert providers["classify"] is not providers["evaluate"]


# ----------------------------------------------------------------- pipeline


def test_each_node_records_the_model_that_actually_answered_it(conn):
    """A split run has to stay legible afterwards: rows carry their own model."""
    cheap = Recording("rule", "small")
    strong = Recording("rule", "large")
    stats = pipeline.process(
        conn,
        [RawArticle(source="test", url="https://example.test/split",
                    title="حمله موشکی و جهش قیمت طلا در بازار تهران",
                    lead="گزارش خبرگزاری از بازار",
                    content="متن کامل خبر درباره حمله و اثر آن بر قیمت طلا و دلار در بازار داخلی.")],
        {"classify": cheap, "evaluate": strong, "summarize": cheap},
    )
    assert stats["classified"] == 1 and stats["evaluated"] == 1

    assert cheap.calls == ["classify", "summarize"]
    assert strong.calls == ["evaluate"]
    assert conn.execute("SELECT model FROM classifications").fetchone()["model"] == "small"
    assert conn.execute("SELECT model FROM evaluations").fetchone()["model"] == "large"
    assert conn.execute("SELECT model FROM summaries").fetchone()["model"] == "small"


def test_a_single_provider_still_serves_every_node(conn):
    """The pre-routing call signature stays valid; nothing had to be migrated."""
    provider = Recording("rule", "solo")
    pipeline.process(
        conn,
        [RawArticle(source="test", url="https://example.test/solo",
                    title="حمله موشکی و جهش قیمت طلا در بازار تهران",
                    lead="گزارش خبرگزاری از بازار",
                    content="متن کامل خبر درباره حمله و اثر آن بر قیمت طلا و دلار در بازار داخلی.")],
        provider,
    )
    assert sorted(provider.calls) == ["classify", "evaluate", "summarize"]


def test_an_incomplete_routing_map_is_refused_before_any_call(conn):
    with pytest.raises(config.ConfigError, match="evaluate"):
        pipeline.process(conn, [], {"classify": RuleProvider(), "summarize": RuleProvider()})


def test_changing_one_nodes_model_reruns_only_that_node(conn):
    """The existence check is keyed on provider+model, so a swap is not a full re-run."""
    article = RawArticle(source="test", url="https://example.test/rerun",
                         title="حمله موشکی و جهش قیمت طلا در بازار تهران",
                         lead="گزارش خبرگزاری از بازار",
                         content="متن کامل خبر درباره حمله و اثر آن بر قیمت طلا و دلار در بازار داخلی.")
    first = {name: RuleProvider(name="rule", model="v1") for name in ("classify", "evaluate", "summarize")}
    pipeline.process(conn, [article], first)

    swapped = dict(first)
    swapped["evaluate"] = RuleProvider(name="rule", model="v2")
    stats = pipeline.process(conn, [article], swapped)

    assert stats["classified"] == 0, "classify was unchanged and must not be paid for again"
    assert stats["evaluated"] == 1, "evaluate moved to a new model and must re-run"
    assert [row["model"] for row in conn.execute("SELECT model FROM evaluations ORDER BY id")] == ["v1", "v2"]


def test_describe_reports_node_to_model():
    assert routing.describe({"classify": RuleProvider(name="rule", model="small")}) == {
        "classify": "rule:small"
    }
