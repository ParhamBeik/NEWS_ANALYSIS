"""Unit tests for the node runtime.

Unit rather than integration: these exercise pure control flow (retry, caching, budget,
error routing) with no network and no LLM, so they run in milliseconds and can gate every
commit. The pipeline wiring gets an integration test against FakeProvider later.
"""

from dataclasses import dataclass

import pytest

from news_intel.core import dag


@dataclass
class Item:
    content_hash: str = "abc"
    prompt_version: str = "v1"


def events(conn, status=None):
    sql = "SELECT * FROM node_events"
    args = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    return conn.execute(sql + " ORDER BY id", args).fetchall()


# ------------------------------------------------------------------ retry taxonomy


def test_transient_retries_then_succeeds(ctx, conn):
    calls = []

    @dag.node(name="flaky", retries=2, backoff=0)
    def flaky(item, ctx):
        calls.append(1)
        if len(calls) < 3:
            raise dag.Transient("502 upstream")
        return "ok"

    result = flaky(Item(), ctx)

    assert result.value == "ok"
    assert result.attempts == 3
    assert len(calls) == 3
    assert [e["status"] for e in events(conn)] == ["retry", "retry", "success"]


def test_transient_exhausts_and_dead_letters(ctx, conn, article_id):
    @dag.node(name="down", retries=1, backoff=0)
    def down(item, ctx):
        raise dag.Transient("connection refused")

    with pytest.raises(dag.Transient):
        down(Item(), ctx, article_id=article_id)

    assert [e["status"] for e in events(conn)] == ["retry", "exhausted"]
    dead = conn.execute("SELECT * FROM dead_letters").fetchall()
    assert len(dead) == 1
    assert dead[0]["error_class"] == "Transient"


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
    assert [e["status"] for e in events(conn)] == ["permanent"]
    assert conn.execute("SELECT COUNT(*) c FROM dead_letters").fetchone()["c"] == 1


def test_unknown_exception_is_permanent_not_transient(ctx, conn):
    """Retrying an error you do not understand is how a bug becomes a spend loop."""
    calls = []

    @dag.node(name="weird", retries=3, backoff=0)
    def weird(item, ctx):
        calls.append(1)
        raise ValueError("something unmodelled")

    with pytest.raises(dag.Permanent):
        weird(Item(), ctx)
    assert len(calls) == 1


def test_timeout_is_classified_transient():
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

    assert [e["status"] for e in events(conn)] == ["fatal"]
    assert conn.execute("SELECT COUNT(*) c FROM dead_letters").fetchone()["c"] == 0


# -------------------------------------------------------------------------- caching


def test_second_call_hits_cache(ctx, conn):
    calls = []

    @dag.node(name="classify", version="v4", cache_on=("content_hash", "prompt_version"))
    def classify(item, ctx):
        calls.append(1)
        return "security"

    first = classify(Item(), ctx)
    second = classify(Item(), ctx)

    assert first.cached is False and first.value == "security"
    assert second.cached is True
    assert len(calls) == 1, "cached call must not invoke the node body"
    assert [e["status"] for e in events(conn)] == ["success", "cache_hit"]


def test_cache_key_changes_with_prompt_version(ctx):
    """Editing a prompt must invalidate exactly that node, and nothing else."""
    calls = []

    @dag.node(name="classify", cache_on=("content_hash", "prompt_version"))
    def classify(item, ctx):
        calls.append(1)
        return "ok"

    classify(Item(prompt_version="v1"), ctx)
    classify(Item(prompt_version="v1"), ctx)
    classify(Item(prompt_version="v2"), ctx)

    assert len(calls) == 2, "v2 is a different key and must recompute"


def test_different_content_is_a_different_key(ctx):
    calls = []

    @dag.node(name="n", cache_on=("content_hash",))
    def n(item, ctx):
        calls.append(1)
        return "ok"

    n(Item(content_hash="a"), ctx)
    n(Item(content_hash="b"), ctx)
    assert len(calls) == 2


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

    removed = dag.invalidate(conn, "classify")
    assert removed == 1

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


# --------------------------------------------------------------------------- budget


def test_budget_ceiling_is_enforced(ctx):
    ctx.costs.charge("classify", 1000, 100, 0.99)

    @dag.node(name="n", cacheable=False)
    def n(item, ctx):
        return "ok"

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


# ------------------------------------------------------------------------- map_node


def test_map_node_isolates_per_item_failure(ctx):
    """One bad article must not abandon the rest of the cycle."""

    @dag.node(name="n", retries=0, backoff=0, cacheable=False)
    def n(item, ctx):
        if item.content_hash == "bad":
            raise dag.Permanent("unparseable")
        return item.content_hash.upper()

    items = [Item("a"), Item("bad"), Item("c")]
    outcome = dag.map_node(n, items, ctx, workers=3)

    assert outcome.succeeded == 2
    assert outcome.failed == 1
    assert outcome.results == ["A", None, "C"]
    assert isinstance(outcome.errors[0][1], dag.Permanent)


def test_map_node_propagates_fatal(ctx):
    @dag.node(name="n", retries=0, backoff=0, cacheable=False)
    def n(item, ctx):
        raise dag.Fatal("budget gone")

    with pytest.raises(dag.Fatal):
        dag.map_node(n, [Item("a")], ctx, workers=2)


def test_map_node_is_thread_safe_under_concurrency(ctx, conn):
    """Node workers write events from several threads onto one sqlite connection."""

    @dag.node(name="n", cacheable=False)
    def n(item, ctx):
        return item.content_hash

    items = [Item(f"h{i}") for i in range(50)]
    outcome = dag.map_node(n, items, ctx, workers=8)

    assert outcome.succeeded == 50
    assert outcome.failed == 0
    assert conn.execute(
        "SELECT COUNT(*) c FROM node_events WHERE status='success'"
    ).fetchone()["c"] == 50


def test_map_node_handles_empty_input(ctx):
    @dag.node(name="n", cacheable=False)
    def n(item, ctx):
        return "x"

    outcome = dag.map_node(n, [], ctx)
    assert outcome.results == [] and outcome.succeeded == 0


# ----------------------------------------------------------------------- dry-run


def test_dry_run_writes_nothing(ctx, conn):
    ctx.dry_run = True

    @dag.node(name="n", cache_on=("content_hash",))
    def n(item, ctx):
        return "ok"

    assert n(Item(), ctx).value == "ok"
    assert events(conn) == []


# --------------------------------------------------------------------------- runs


def test_run_lifecycle_records_totals(conn):
    ctx = dag.Ctx(conn=conn, run_id="r1", costs=dag.CostMeter(budget_usd=5.0))
    dag.start_run(conn, "r1", "live")
    ctx.costs.charge("classify", 500, 50, 0.03)
    dag.finish_run(conn, "r1", ctx.costs, fetched=10, processed=8)

    row = conn.execute("SELECT * FROM runs WHERE run_id='r1'").fetchone()
    assert row["status"] == "success"
    assert row["articles_processed"] == 8
    assert row["cost_usd"] == pytest.approx(0.03)
    assert row["tokens_in"] == 500
    assert row["finished_at"]
