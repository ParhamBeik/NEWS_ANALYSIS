from news_intel import telemetry
from news_intel.core import dag, db

# `days=1` windows filter on `date('now', ...)`, so fixtures must be timestamped against
# the actual clock - a fixed literal here passes today and silently starts failing every
# subsequent day once "now" moves past it.
NOW = dag.utc_now()


def _article(conn, *, source, url, duplicate_of=None):
    return db.insert(conn, "articles", {
        "url": url, "identity_key": f"id:{url}", "source": source,
        "original_title": "t", "lead": "l", "content": "c", "content_hash": url,
        "fetched_at": NOW, "duplicate_of": duplicate_of,
    })


def _event(conn, *, node, status, provider="gapgpt", model="m1", tokens_in=10, tokens_out=5, cost=0.01):
    db.insert(conn, "node_events", {
        "run_id": "r1", "node": node, "node_version": "v1", "cache_key": "k",
        "status": status, "attempt": 1, "tokens_in": tokens_in, "tokens_out": tokens_out,
        "cost_usd": cost, "provider": provider, "model": model, "created_at": NOW,
    })


def test_token_cost_by_day_sums_across_events(conn):
    _event(conn, node="classify", status="success")
    _event(conn, node="evaluate", status="success", tokens_in=20, tokens_out=8, cost=0.02)
    rows = telemetry.token_cost_by_day(conn, days=1)
    assert len(rows) == 1
    assert rows[0]["tokens_in"] == 30 and rows[0]["tokens_out"] == 13
    assert round(rows[0]["cost_usd"], 2) == 0.03


def test_node_status_counts_breaks_out_by_node_and_status(conn):
    _event(conn, node="classify", status="success")
    _event(conn, node="classify", status="success")
    _event(conn, node="classify", status="exhausted")
    rows = {(r["node"], r["status"]): r["n"] for r in telemetry.node_status_counts(conn, days=1)}
    assert rows[("classify", "success")] == 2
    assert rows[("classify", "exhausted")] == 1


def test_provider_breakdown_groups_by_provider_and_model(conn):
    _event(conn, node="classify", status="success", provider="gapgpt", model="a")
    _event(conn, node="classify", status="success", provider="ollama", model="b")
    rows = {(r["provider"], r["model"]): r["calls"] for r in telemetry.provider_breakdown(conn, days=1)}
    assert rows[("gapgpt", "a")] == 1 and rows[("ollama", "b")] == 1


def test_fetch_volume_by_source_counts_articles(conn):
    _article(conn, source="khabarfoori", url="https://t/1")
    _article(conn, source="khabarfoori", url="https://t/2")
    _article(conn, source="mehr", url="https://t/3")
    rows = {r["source"]: r["n"] for r in telemetry.fetch_volume_by_source(conn, days=1)}
    assert rows["khabarfoori"] == 2 and rows["mehr"] == 1


def test_funnel_excludes_duplicates_from_unique_but_not_fetched(conn):
    canonical = _article(conn, source="khabarfoori", url="https://t/1")
    _article(conn, source="khabarfoori", url="https://t/2", duplicate_of=canonical)
    funnel = telemetry.funnel(conn, days=1)
    assert funnel["fetched"] == 2
    assert funnel["unique"] == 1


def test_funnel_counts_classified_and_evaluated_articles(conn):
    article_id = _article(conn, source="khabarfoori", url="https://t/1")
    db.insert(conn, "classifications", {
        "article_id": article_id, "category": "economics", "confidence": "زیاد",
        "method": "llm", "prompt_version": "v1", "provider": "gapgpt", "model": "m1",
        "run_id": "r1", "created_at": NOW,
    })
    funnel = telemetry.funnel(conn, days=1)
    assert funnel["classified"] == 1 and funnel["evaluated"] == 0


def test_source_coverage_flags_which_sources_can_backfill(conn):
    conn.execute(
        "INSERT INTO sources(name, tier, config_path, priority, enabled)"
        " VALUES('khabarfoori', 2, 'x', 1, 1), ('shahrekhabar', 2, 'x', 3, 1)"
    )
    rows = {r["source"]: r for r in telemetry.source_coverage(conn, days=2)}
    assert rows["khabarfoori"]["backfill_supported"] is True
    assert rows["shahrekhabar"]["backfill_supported"] is False
    assert rows["khabarfoori"]["missing_days"] == 2
