"""Pipeline operational telemetry: tokens, cost, LLM success rate, fetch/coverage health.

Distinct from `metrics.py`, which is scoped to model-vs-human label agreement. Everything
here reads `node_events`/`articles`, which already carry every number needed - this module
only aggregates, it adds no new storage.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import backfill
from . import sources as sources_module


def _floor(days: int) -> str:
    return f"-{max(days, 1) - 1} days"


def token_cost_by_day(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT date(created_at) AS day, SUM(tokens_in) AS tokens_in,"
        " SUM(tokens_out) AS tokens_out, SUM(cost_usd) AS cost_usd"
        " FROM node_events WHERE created_at >= date('now', ?)"
        " GROUP BY day ORDER BY day",
        (_floor(days),),
    ).fetchall()
    return [dict(row) for row in rows]


def node_status_counts(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT node, status, COUNT(*) AS n FROM node_events"
        " WHERE created_at >= date('now', ?) GROUP BY node, status ORDER BY node, status",
        (_floor(days),),
    ).fetchall()
    return [dict(row) for row in rows]


def provider_breakdown(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT provider, model, COUNT(*) AS calls, SUM(tokens_in) AS tokens_in,"
        " SUM(tokens_out) AS tokens_out, SUM(cost_usd) AS cost_usd"
        " FROM node_events WHERE created_at >= date('now', ?) AND provider IS NOT NULL"
        " GROUP BY provider, model ORDER BY cost_usd DESC",
        (_floor(days),),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_volume_by_source(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT source, date(fetched_at) AS day, COUNT(*) AS n FROM articles"
        " WHERE fetched_at >= date('now', ?) GROUP BY source, day ORDER BY day, source",
        (_floor(days),),
    ).fetchall()
    return [dict(row) for row in rows]


def funnel(conn: sqlite3.Connection, days: int) -> dict[str, int]:
    floor = _floor(days)
    fetched = conn.execute(
        "SELECT COUNT(*) c FROM articles WHERE fetched_at >= date('now', ?)", (floor,)
    ).fetchone()["c"]
    unique = conn.execute(
        "SELECT COUNT(*) c FROM articles WHERE fetched_at >= date('now', ?) AND duplicate_of IS NULL",
        (floor,),
    ).fetchone()["c"]
    classified = conn.execute(
        "SELECT COUNT(DISTINCT a.id) c FROM articles a JOIN classifications cl ON cl.article_id = a.id"
        " WHERE a.fetched_at >= date('now', ?) AND a.duplicate_of IS NULL",
        (floor,),
    ).fetchone()["c"]
    evaluated = conn.execute(
        "SELECT COUNT(DISTINCT a.id) c FROM articles a JOIN evaluations e ON e.article_id = a.id"
        " WHERE a.fetched_at >= date('now', ?) AND a.duplicate_of IS NULL",
        (floor,),
    ).fetchone()["c"]
    return {"fetched": fetched, "unique": unique, "classified": classified, "evaluated": evaluated}


def source_coverage(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    """Per-source rolling-window completeness, honest about which sources can't backfill."""
    names = [row["name"] for row in conn.execute("SELECT name FROM sources WHERE enabled=1")]
    return [
        {
            "source": name,
            "missing_days": len(backfill.coverage(conn, name, days)),
            "total_days": days,
            "backfill_supported": name in sources_module._BACKFILL_STRATEGIES,
        }
        for name in names
    ]
