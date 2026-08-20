"""Node runtime and configuration.

Unit rather than integration: pure control flow (retry, caching, budget, error routing)
with no network and no LLM, so it runs in milliseconds and can gate every commit.
"""

from dataclasses import dataclass

import pytest

from news_intel import config, dag


@dataclass
class Item:
    content_hash: str = "abc"
    prompt_version: str = "v1"


def statuses(conn):
    return [row["status"] for row in conn.execute("SELECT status FROM node_events ORDER BY id")]


def dead_letters(conn):
    return conn.execute("SELECT * FROM dead_letters").fetchall()


# ------------------------------------------------------------------- retry taxonomy


def test_transient_retries_then_succeeds(ctx, conn):
    calls = []

    @dag.node(name="flaky", retries=2, backoff=0)
    def flaky(item, ctx):
        calls.append(1)
        if len(calls) < 3:
            raise dag.Transient("502 upstream")
        return "ok"

    result = flaky(Item(), ctx)
    assert (result.value, result.attempts, len(calls)) == ("ok", 3, 3)
    assert statuses(conn) == ["retry", "retry", "success"]


def test_transient_exhausts_and_dead_letters(ctx, conn, article_id):
    @dag.node(name="down", retries=1, backoff=0)
    def down(item, ctx):
        raise dag.Transient("connection refused")

    with pytest.raises(dag.Transient):
        down(Item(), ctx, article_id=article_id)

    assert statuses(conn) == ["retry", "exhausted"]
    assert [row["error_class"] for row in dead_letters(conn)] == ["Transient"]


def test_permanent_does_not_retry(ctx, conn, article_id):
    """The 465-stuck-article bug: legacy retried every failure forever, with no taxonomy."""
    calls = []

    @dag.node(name="bad", retries=5, backoff=0)
    def bad(item, ctx):
        calls.append(1)
        raise dag.Permanent("article has no body")

    with pytest.raises(dag.Permanent):
        bad(Item(), ctx, article_id=article_id)

    assert len(calls) == 1, "Permanent must not be retried"
    assert statuses(conn) == ["permanent"]
    assert len(dead_letters(conn)) == 1


def test_unknown_exception_is_permanent_not_transient(ctx):
    """Retrying an error you do not understand is how a bug becomes a spend loop."""
    calls = []

    @dag.node(name="weird", retries=3, backoff=0)
    def weird(item, ctx):
        calls.append(1)
        raise ValueError("something unmodelled")

    with pytest.raises(dag.Permanent):
        weird(Item(), ctx)
    assert len(calls) == 1


def test_exception_classification():
    assert dag.classify_exception(TimeoutError("slow")) is dag.Transient
    assert dag.classify_exception(ConnectionResetError("reset")) is dag.Transient
    assert dag.classify_exception(ValueError("nope")) is dag.Permanent
    assert dag.classify_exception(dag.Fatal("bad key")) is dag.Fatal


def test_fatal_aborts_without_dead_letter(ctx, conn, article_id):
    @dag.node(name="auth", retries=3, backoff=0)
    def auth(item, ctx):
        raise dag.Fatal("401 invalid api key")

    with pytest.raises(dag.Fatal):
        auth(Item(), ctx, article_id=article_id)

    assert statuses(conn) == ["fatal"]
    assert dead_letters(conn) == []


# --------------------------------------------------------------------------- caching


def test_second_call_hits_cache(ctx, conn):
    calls = []

    @dag.node(name="classify", version="v4", cache_on=("content_hash", "prompt_version"))
    def classify(item, ctx):
        calls.append(1)
        return "security"

    first, second = classify(Item(), ctx), classify(Item(), ctx)
    assert first.cached is False and first.value == "security"
    assert second.cached is True
    assert len(calls) == 1, "a cached call must not invoke the node body"
    assert statuses(conn) == ["success", "cache_hit"]


@pytest.mark.parametrize("field,values", [
    ("prompt_version", ("v1", "v1", "v2")),   # editing a prompt invalidates that node
    ("content_hash", ("a", "a", "b")),        # different article, different key
])
def test_cache_key_covers_every_declared_field(ctx, field, values):
    calls = []

    @dag.node(name="n", cache_on=("content_hash", "prompt_version"))
    def n(item, ctx):
        calls.append(1)
        return "ok"

    for value in values:
        n(Item(**{field: value}), ctx)
    assert len(calls) == 2, "only the changed key recomputes"


def test_failures_are_not_cached(ctx):
    calls = []

    @dag.node(name="n", retries=0, backoff=0, cache_on=("content_hash",))
    def n(item, ctx):
        calls.append(1)
        raise dag.Permanent("boom")

    for _ in range(2):
        with pytest.raises(dag.Permanent):
            n(Item(), ctx)
    assert len(calls) == 2, "only successes are cached"


def test_invalidate_forces_recompute(ctx, conn):
    calls = []

    @dag.node(name="classify", version="v4", cache_on=("content_hash",))
    def classify(item, ctx):
        calls.append(1)
        return "ok"

    classify(Item(), ctx)
    assert classify(Item(), ctx).cached is True
    assert dag.invalidate(conn, "classify") == 1
    assert classify(Item(), ctx).cached is False
    assert len(calls) == 2


def test_uncacheable_node_always_runs(ctx):
    calls = []

    @dag.node(name="fetch", cacheable=False)
    def fetch(item, ctx):
        calls.append(1)
        return "ok"

    fetch(Item(), ctx)
    fetch(Item(), ctx)
    assert len(calls) == 2


def test_dry_run_writes_nothing(ctx, conn):
    ctx.dry_run = True

    @dag.node(name="n", cache_on=("content_hash",))
    def n(item, ctx):
        return "ok"

    assert n(Item(), ctx).value == "ok"
    assert statuses(conn) == []


# ---------------------------------------------------------------------------- budget


def test_budget_ceiling_is_enforced(ctx):
    @dag.node(name="n", cacheable=False)
    def n(item, ctx):
        return "ok"

    ctx.costs.charge("classify", 1000, 100, 0.99)
    n(Item(), ctx)  # still under $1.00
    ctx.costs.charge("classify", 1000, 100, 0.02)
    with pytest.raises(dag.BudgetExceeded):
        n(Item(), ctx)


def test_cost_is_tracked_per_node(ctx):
    ctx.costs.charge("classify", 100, 10, 0.01)
    ctx.costs.charge("evaluate", 200, 20, 0.02)
    ctx.costs.charge("classify", 100, 10, 0.01)
    assert ctx.costs.cost_usd == pytest.approx(0.04)
    assert ctx.costs.tokens_in == 400
    assert ctx.costs.by_node["classify"]["cost_usd"] == pytest.approx(0.02)
    assert ctx.costs.by_node["evaluate"]["tokens_out"] == 20


# ------------------------------------------------------------------------------ runs


def test_run_lifecycle_records_totals(conn):
    costs = dag.CostMeter(budget_usd=5.0)
    dag.start_run(conn, "r1", "live")
    costs.charge("classify", 500, 50, 0.03)
    dag.finish_run(conn, "r1", costs, fetched=10, processed=8)

    row = conn.execute("SELECT * FROM runs WHERE run_id='r1'").fetchone()
    assert row["status"] == "success"
    assert row["articles_processed"] == 8
    assert row["cost_usd"] == pytest.approx(0.03)
    assert row["tokens_in"] == 500
    assert row["finished_at"]


def test_run_ids_started_in_the_same_second_do_not_collide():
    """`runs.run_id` is UNIQUE and second resolution is not, so two runs a moment apart
    used to collide on insert and take the whole run down with an IntegrityError."""
    assert dag.new_run_id() != dag.new_run_id()


# ---------------------------------------------------------------------------- config


def test_load_dotenv_populates_missing_environment_only(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("GAPGPT_API_KEY=test-key\nEXISTING=from-file\n", encoding="utf-8")
    monkeypatch.delenv("GAPGPT_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING", "from-environment")

    config.load_dotenv(path)
    assert config.require_env("GAPGPT_API_KEY") == "test-key"
    assert config.env("EXISTING", "") == "from-environment"


def test_the_default_call_cap_clears_a_full_cycle(monkeypatch):
    """The cap is per run, not per article. A cycle of 25 articles issues up to 3 requests
    each; a cap below that aborts the run with a Fatal error, and run_loop stops the daemon
    on Fatal - so a "safety" default set too low silently ends the continuous fetching."""
    monkeypatch.delenv("NEWS_MAX_PROVIDER_CALLS", raising=False)
    assert config.provider_max_calls() >= 25 * 3


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_an_invalid_call_cap_is_refused(monkeypatch, value):
    monkeypatch.setenv("NEWS_MAX_PROVIDER_CALLS", value)
    with pytest.raises(config.ConfigError):
        config.provider_max_calls()
