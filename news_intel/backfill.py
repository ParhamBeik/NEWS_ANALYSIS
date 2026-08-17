"""Keep the last N days of articles per source complete, automatically.

Two clocks matter here and they're deliberately not the same one: gap detection reads
`published_at_persian` (Jalali, matching what the team's own workbook uses and what
`coverage()` compares against), while the fetch-side floor passed to
`sources.backfill_fetch` is a plain Gregorian ISO date, because that's the format
`RawArticle.published_at` actually carries.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import jdatetime

from . import pipeline, sources
from .core import db

# Skip re-attempting a source whose gap didn't close on the last try. Prevents hammering
# a source every cycle over a gap that's structurally unfillable (e.g. no article was
# published that day at all), at the cost of a stale gap taking up to this long to retry.
_RETRY_COOLDOWN_HOURS = 6


def _jalali_str(value: jdatetime.date) -> str:
    return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"


def _window_dates(days: int) -> list[str]:
    today = jdatetime.date.today()
    return [_jalali_str(today - timedelta(days=offset)) for offset in range(days)]


def coverage(conn: sqlite3.Connection, source: str, days: int) -> set[str]:
    """Jalali dates in the last `days` days with no canonical, dated article for `source`."""
    window = _window_dates(days)
    rows = conn.execute(
        "SELECT DISTINCT published_at_persian FROM articles"
        " WHERE source=? AND date_uncertain=0 AND duplicate_of IS NULL"
        " AND published_at_persian >= ?",
        (source, min(window)),
    ).fetchall()
    present = {row["published_at_persian"] for row in rows}
    return set(window) - present


def _known_urls(conn: sqlite3.Connection, source: str) -> set[str]:
    return {row["url"] for row in conn.execute("SELECT url FROM articles WHERE source=?", (source,))}


def ensure_window(
    conn: sqlite3.Connection,
    specs: dict[str, sources.SourceSpec],
    providers,
    *,
    days: int,
) -> dict[str, int]:
    """Backfill any enabled source with a registered history mechanism that has a gap.

    Discovered articles go through the normal `pipeline.process()` path - same
    dedup/classify/evaluate as an incremental fetch, just sourced from older pages.
    Cheap when the window is already whole: `coverage()` is one indexed query per
    source, and the (possibly slow) pagination only runs when a gap is found.
    """
    stats: dict[str, int] = {}
    since_date = (date.today() - timedelta(days=days - 1)).isoformat()
    now = datetime.now(timezone.utc)
    for name, spec in specs.items():
        if not spec.enabled or name not in sources._BACKFILL_STRATEGIES:
            continue
        if not coverage(conn, name, days):
            continue
        last = db.get_setting(conn, f"backfill_last_run:{name}", "")
        if last and now - datetime.fromisoformat(last) < timedelta(hours=_RETRY_COOLDOWN_HOURS):
            continue
        known = _known_urls(conn, name)
        articles = list(sources.backfill_fetch(spec, since_date=since_date, known_urls=known))
        if articles:
            pipeline.process(conn, articles, providers)
        with conn:
            db.set_setting(conn, f"backfill_last_run:{name}", now.isoformat())
        stats[name] = len(articles)
    return stats
