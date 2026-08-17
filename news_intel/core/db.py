"""SQLite storage.

Replaces the legacy 41 MB JSON blob that had to be fully re-serialized to persist a
single article. Two structural choices matter:

1. Inference results live in their own tables, not flattened onto the article. Re-running
   classification with a new prompt or a different provider APPENDS a row instead of
   destroying the previous answer. That is what makes prompt A/B testing, provider
   comparison and evaluation possible at all.

2. Ordinal score columns are NULLABLE and never defaulted. Legacy mapped a missing level
   to "متوسط" (the middle value), so security articles carried a fabricated gold-impact
   score on an axis no model had assessed - and that value fed the notify decision.
   Here, missing means NULL and the scoring rule handles it explicitly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from . import config

SCHEMA_VERSION = 1

# Ordinal scale, weakest to strongest. Kept in a table so SQL aggregations can join
# against it rather than duplicating the mapping in queries.
LEVELS: tuple[str, ...] = ("خیلی کم", "کم", "متوسط", "زیاد", "خیلی زیاد")

SCHEMA = """
CREATE TABLE IF NOT EXISTS levels (
    level TEXT PRIMARY KEY,
    score INTEGER NOT NULL
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
    -- Which adapter fetched it (khabarfoori/mehr/...). The crawl origin.
    source                  TEXT NOT NULL,
    -- The outlet credited by the page. Khabarfoori is an aggregator, so this is often a
    -- different agency (فارس، ایسنا، مهر...). Keeping both separate is what makes dedup
    -- possible once we crawl Mehr directly and meet its stories again via Khabarfoori.
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

-- One row per node execution. Doubles as the cache index and the dashboard's data source.
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
-- The cache lookup is the hottest query in the system; this index serves it directly.
CREATE INDEX IF NOT EXISTS idx_events_cache
    ON node_events(node, node_version, cache_key, status);
CREATE INDEX IF NOT EXISTS idx_events_run     ON node_events(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_article ON node_events(article_id);

-- Human review is the only source eligible for prompt examples and evaluation truth.
CREATE TABLE IF NOT EXISTS review_cases (
    id                  INTEGER PRIMARY KEY,
    article_id          INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    stratum             TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    reviewed_category   TEXT,
    confidence_occurrence TEXT REFERENCES levels(level),
    gold_price_impact   TEXT REFERENCES levels(level),
    security_relevance  TEXT REFERENCES levels(level),
    gold_trend          TEXT,
    one_line            TEXT,
    reviewer_notes      TEXT,
    reviewed_at         TEXT,
    created_at          TEXT NOT NULL
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

-- "Latest inference wins" without scattering max(created_at) through every query.
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
    """Open the database.

    readonly=True is what the dashboard uses. A monitoring tool that can lock the thing
    it monitors is worse than no monitoring tool.
    """
    path = path or config.DB_PATH
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because node workers run in a ThreadPoolExecutor.
        # Writes are serialized by Ctx.lock in dag.py - sqlite3 will not do it for us.
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
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    return conn


def level_score(level: str | None) -> int | None:
    """Ordinal position of a level, or None if absent/unrecognised.

    Returns None rather than a middle default - that substitution is the legacy bug
    this module's docstring describes.
    """
    if not level:
        return None
    try:
        return LEVELS.index(level) + 1
    except ValueError:
        return None


def insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
    return int(cur.lastrowid)


def insert_many(conn: sqlite3.Connection, table: str, rows: Iterable[dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    cols = ", ".join(rows[0])
    marks = ", ".join("?" for _ in rows[0])
    conn.executemany(
        f"INSERT INTO {table} ({cols}) VALUES ({marks})",
        [tuple(r[c] for c in rows[0]) for r in rows],
    )
    return len(rows)
