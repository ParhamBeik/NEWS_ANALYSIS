"""SQLite storage.

Two structural choices matter:

1. Inference results live in their own tables, not flattened onto the article. Re-running
   with a new prompt or provider APPENDS a row. That is what makes A/B comparison and
   provider evaluation possible at all.
2. Ordinal score columns are NULLABLE and never defaulted. Missing means NULL; see
   scoring.py for why substituting a level there is the bug this rebuild exists to fix.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import jdatetime

from . import config, text
from .scoring import LEVELS

SCHEMA = """
CREATE TABLE IF NOT EXISTS levels (
    level TEXT PRIMARY KEY,
    score INTEGER NOT NULL
);

-- Small knobs the dashboard edits without a restart (e.g. rolling_window_days).
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    name            TEXT PRIMARY KEY,
    tier            INTEGER NOT NULL,
    config_path     TEXT,
    priority        INTEGER NOT NULL DEFAULT 100,
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_success_at TEXT,
    last_error      TEXT,
    health_status   TEXT NOT NULL DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS articles (
    id                      INTEGER PRIMARY KEY,
    url                     TEXT NOT NULL UNIQUE,
    identity_key            TEXT NOT NULL,
    source                  TEXT NOT NULL,   -- which adapter fetched it
    -- The outlet credited by the page. Khabarfoori is an aggregator, so this is often a
    -- different agency; keeping both separate is what makes cross-source dedup possible.
    original_outlet         TEXT,
    original_title          TEXT NOT NULL DEFAULT '',
    lead                    TEXT NOT NULL DEFAULT '',
    content                 TEXT NOT NULL DEFAULT '',
    content_hash            TEXT NOT NULL,
    published_at_gregorian  TEXT,
    published_at_persian    TEXT,
    published_time          TEXT,
    date_uncertain          INTEGER NOT NULL DEFAULT 0,
    fetched_at              TEXT NOT NULL,
    first_seen_run          TEXT,
    last_seen_run           TEXT,
    extraction_tier         TEXT,
    quality_flags           TEXT,
    duplicate_of            INTEGER REFERENCES articles(id)
);
CREATE INDEX IF NOT EXISTS idx_articles_identity ON articles(identity_key);
CREATE INDEX IF NOT EXISTS idx_articles_hash     ON articles(content_hash);
CREATE INDEX IF NOT EXISTS idx_articles_persian  ON articles(published_at_persian);
CREATE INDEX IF NOT EXISTS idx_articles_source   ON articles(source, published_at_gregorian);
CREATE INDEX IF NOT EXISTS idx_articles_outlet   ON articles(original_outlet);
CREATE INDEX IF NOT EXISTS idx_articles_dup      ON articles(duplicate_of);

CREATE TABLE IF NOT EXISTS classifications (
    id              INTEGER PRIMARY KEY,
    article_id      INTEGER NOT NULL REFERENCES articles(id),
    category        TEXT NOT NULL,
    confidence      TEXT REFERENCES levels(level),
    rationale       TEXT,
    memory_keywords TEXT,
    memory_logic    TEXT,
    keyword_hits    TEXT,
    method          TEXT NOT NULL DEFAULT 'llm',
    prompt_version  TEXT,
    provider        TEXT,
    model           TEXT,
    run_id          TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cls_article ON classifications(article_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cls_run     ON classifications(run_id);

-- Score columns are nullable on purpose. NULL means "not assessed", never "average".
CREATE TABLE IF NOT EXISTS evaluations (
    id                    INTEGER PRIMARY KEY,
    article_id            INTEGER NOT NULL REFERENCES articles(id),
    confidence_occurrence TEXT REFERENCES levels(level),
    gold_price_impact     TEXT REFERENCES levels(level),
    security_relevance    TEXT REFERENCES levels(level),
    gold_trend            TEXT,
    rationale             TEXT,
    prompt_version        TEXT,
    provider              TEXT,
    model                 TEXT,
    run_id                TEXT,
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_article ON evaluations(article_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eval_run     ON evaluations(run_id);

CREATE TABLE IF NOT EXISTS summaries (
    id              INTEGER PRIMARY KEY,
    article_id      INTEGER NOT NULL REFERENCES articles(id),
    optimized_title TEXT,
    one_line        TEXT,
    prompt_version  TEXT,
    provider        TEXT,
    model           TEXT,
    run_id          TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sum_article ON summaries(article_id, created_at DESC);

CREATE TABLE IF NOT EXISTS runs (
    run_id             TEXT PRIMARY KEY,
    mode               TEXT NOT NULL,
    status             TEXT NOT NULL,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    articles_fetched   INTEGER NOT NULL DEFAULT 0,
    articles_processed INTEGER NOT NULL DEFAULT 0,
    cost_usd           REAL NOT NULL DEFAULT 0,
    tokens_in          INTEGER NOT NULL DEFAULT 0,
    tokens_out         INTEGER NOT NULL DEFAULT 0,
    error              TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);

-- One row per node execution: the cache index and the dashboard's data source at once.
CREATE TABLE IF NOT EXISTS node_events (
    id           INTEGER PRIMARY KEY,
    run_id       TEXT NOT NULL,
    node         TEXT NOT NULL,
    node_version TEXT NOT NULL,
    article_id   INTEGER REFERENCES articles(id),
    cache_key    TEXT NOT NULL,
    status       TEXT NOT NULL,
    attempt      INTEGER NOT NULL DEFAULT 1,
    latency_ms   INTEGER,
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    cost_usd     REAL NOT NULL DEFAULT 0,
    provider     TEXT,
    model        TEXT,
    error_class  TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_cache
    ON node_events(node, node_version, cache_key, status);
CREATE INDEX IF NOT EXISTS idx_events_run     ON node_events(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_article ON node_events(article_id);

-- Human review is the only source eligible for prompt examples and evaluation truth.
CREATE TABLE IF NOT EXISTS review_cases (
    id                    INTEGER PRIMARY KEY,
    article_id            INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    stratum               TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'pending',
    reviewed_category     TEXT,
    confidence_occurrence TEXT REFERENCES levels(level),
    gold_price_impact     TEXT REFERENCES levels(level),
    security_relevance    TEXT REFERENCES levels(level),
    gold_trend            TEXT,
    one_line              TEXT,
    reviewer_notes        TEXT,
    reviewed_at           TEXT,
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_cases(status, stratum);

CREATE TABLE IF NOT EXISTS dead_letters (
    id             INTEGER PRIMARY KEY,
    article_id     INTEGER NOT NULL REFERENCES articles(id),
    node           TEXT NOT NULL,
    error_class    TEXT NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 1,
    last_error     TEXT,
    quarantined_at TEXT NOT NULL,
    resolved_at    TEXT,
    UNIQUE(article_id, node)
);
CREATE INDEX IF NOT EXISTS idx_dead_open ON dead_letters(resolved_at, node);

-- "Latest inference wins", without max(created_at) scattered through every query.
CREATE VIEW IF NOT EXISTS latest_classification AS
SELECT c.* FROM classifications c
WHERE c.id = (SELECT id FROM classifications
              WHERE article_id = c.article_id ORDER BY created_at DESC, id DESC LIMIT 1);

CREATE VIEW IF NOT EXISTS latest_evaluation AS
SELECT e.* FROM evaluations e
WHERE e.id = (SELECT id FROM evaluations
              WHERE article_id = e.article_id ORDER BY created_at DESC, id DESC LIMIT 1);

CREATE VIEW IF NOT EXISTS latest_summary AS
SELECT s.* FROM summaries s
WHERE s.id = (SELECT id FROM summaries
              WHERE article_id = s.article_id ORDER BY created_at DESC, id DESC LIMIT 1);
"""


def connect(path: Path | None = None, *, readonly: bool = False) -> sqlite3.Connection:
    """Open the database. readonly=True is what the dashboard uses - a monitoring tool
    that can lock the thing it monitors is worse than no monitoring tool."""
    path = path or config.DB_PATH
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because node workers run in a ThreadPoolExecutor. Writes
        # are serialized by dag.Ctx.lock - sqlite3 will not do it for us.
        conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path | None = None) -> sqlite3.Connection:
    conn = connect(path)
    with conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO levels(level, score) VALUES (?, ?)",
            [(level, i + 1) for i, level in enumerate(LEVELS)],
        )
    return conn


def insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
    return int(cur.lastrowid)


def get_setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def window_days(conn: sqlite3.Connection) -> int:
    """The dashboard's rolling-window setting, in days."""
    return int(get_setting(conn, "rolling_window_days", config.DEFAULT_WINDOW_DAYS))


def day_floor(days: int) -> str:
    """SQLite `date('now', ?)` offset string for a rolling N-day window."""
    return f"-{max(days, 1) - 1} days"


def missing_days(conn: sqlite3.Connection, source: str, days: int) -> set[str]:
    """Jalali dates in the window with no canonical, dated article for `source`.

    Gap detection reads Jalali because that is what the team's workbook uses; the floor
    handed to sources.backfill_fetch is Gregorian because that is what RawArticle carries.
    """
    today = jdatetime.date.today()
    window = {text.jalali_str(today - timedelta(days=offset)) for offset in range(days)}
    present = {
        row["published_at_persian"]
        for row in conn.execute(
            "SELECT DISTINCT published_at_persian FROM articles"
            " WHERE source=? AND date_uncertain=0 AND duplicate_of IS NULL"
            " AND published_at_persian >= ?",
            (source, min(window)),
        )
    }
    return window - present
