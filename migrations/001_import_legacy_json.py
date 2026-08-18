#!/usr/bin/env python3
"""Import the legacy JSON databases into SQLite.

Legacy stored one flat 41-field record per article. This splits each record into its
real parts: the article, and the separate inference results produced against it.

Both legacy databases are imported. They overlap on URL but were produced by different
prompt versions, so the overlap is not waste - it lands as multiple classification rows
per article and is the first real A/B comparison the system has ever had. The production
database alone spans three prompt generations (v1/v2/v3).

Usage:
    python migrations/001_import_legacy_json.py [--reset]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_intel.core import config, db, normalize  # noqa: E402

LEGACY = config.ROOT / "LEGACY" / "NEWS_AI_PROJECT"
SOURCES = [
    ("legacy_prod", LEGACY / "خبر فوری" / "JSON Files" / "news_database.json"),
    ("legacy_test", LEGACY / "TEST_OUTPUT" / "JSON Files" / "news_database.json"),
]

# Legacy adapter identity: every record in both databases was crawled from khabarfoori,
# whatever outlet the page credited.
ADAPTER = "khabarfoori"


def text(value) -> str:
    return normalize.clean(value if isinstance(value, str) else "")


def level(value) -> str | None:
    """Empty string means the model never answered. Keep it NULL, never average it."""
    cleaned = text(value)
    return cleaned if cleaned in db.LEVELS else None


def jdump(value) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value else None


def import_file(conn, run_id: str, path: Path) -> dict[str, int]:
    records = json.loads(path.read_text(encoding="utf-8"))
    stats = dict(articles=0, reused=0, classifications=0, evaluations=0, summaries=0)
    pending_dupes: list[tuple[str, str]] = []

    conn.execute(
        "INSERT OR REPLACE INTO runs(run_id, mode, status, started_at, finished_at,"
        " articles_fetched, articles_processed) VALUES (?,?,?,?,?,?,?)",
        (run_id, "legacy_import", "success", "", "", len(records), len(records)),
    )

    for url, rec in records.items():
        fetched_at = text(rec.get("fetched_at"))
        title = text(rec.get("original_title"))
        lead = text(rec.get("lead"))
        content = text(rec.get("content"))

        row = conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()
        if row:
            article_id = row["id"]
            stats["reused"] += 1
        else:
            article_id = db.insert(
                conn,
                "articles",
                {
                    "url": url,
                    "identity_key": text(rec.get("url_identity_key")) or f"url:{url}",
                    "source": ADAPTER,
                    "original_outlet": text(rec.get("source")) or None,
                    "original_title": title,
                    "lead": lead,
                    "content": content,
                    "content_hash": normalize.content_hash(title, lead, content),
                    "published_at_gregorian": text(rec.get("published_at_gregorian")) or None,
                    "published_at_persian": text(rec.get("published_at_persian")) or None,
                    "published_time": text(rec.get("published_time")) or None,
                    "date_uncertain": int(bool(rec.get("date_uncertain"))),
                    "fetched_at": fetched_at,
                    "first_seen_run": text(rec.get("first_seen_cycle")) or None,
                    "last_seen_run": text(rec.get("last_seen_cycle")) or None,
                    "extraction_tier": "legacy",
                },
            )
            stats["articles"] += 1

        if rec.get("duplicate_of"):
            pending_dupes.append((url, rec["duplicate_of"]))

        category = text(rec.get("classification_category"))
        if category:
            db.insert(
                conn,
                "classifications",
                {
                    "article_id": article_id,
                    "category": category,
                    "confidence": level(rec.get("classification_confidence")),
                    "rationale": text(rec.get("classification_rationale")) or None,
                    "memory_keywords": jdump(rec.get("classification_memory_keywords")),
                    "memory_logic": text(rec.get("classification_memory_logic")) or None,
                    "keyword_hits": jdump(rec.get("classification_keyword_hits")),
                    "method": text(rec.get("classification_method")) or "llm",
                    "prompt_version": text(rec.get("classification_version")) or None,
                    "provider": "gapgpt",
                    "model": "gemini-2.0-flash-lite",
                    "run_id": run_id,
                    "created_at": fetched_at,
                },
            )
            stats["classifications"] += 1

        if text(rec.get("evaluation_status")) == "success":
            db.insert(
                conn,
                "evaluations",
                {
                    "article_id": article_id,
                    "confidence_occurrence": level(rec.get("confidence_occurrence")),
                    "gold_price_impact": level(rec.get("gold_price_impact")),
                    "security_relevance": level(rec.get("security_relevance")),
                    "gold_trend": text(rec.get("gold_trend")) or None,
                    "prompt_version": text(rec.get("evaluation_version")) or None,
                    "provider": "gapgpt",
                    "model": "gemini-2.0-flash-lite",
                    "run_id": run_id,
                    "created_at": fetched_at,
                },
            )
            stats["evaluations"] += 1

        if text(rec.get("compression_status")) == "success":
            db.insert(
                conn,
                "summaries",
                {
                    "article_id": article_id,
                    "optimized_title": text(rec.get("optimized_title")) or None,
                    "one_line": text(rec.get("one_line_description")) or None,
                    "prompt_version": text(rec.get("compression_version")) or None,
                    "provider": "gapgpt",
                    "model": "gemini-2.0-flash-lite",
                    "run_id": run_id,
                    "created_at": fetched_at,
                },
            )
            stats["summaries"] += 1

    # Second pass: duplicate_of is a URL in legacy, a row id here.
    resolved = 0
    for url, primary_url in pending_dupes:
        primary = conn.execute("SELECT id FROM articles WHERE url = ?", (primary_url,)).fetchone()
        if primary:
            conn.execute(
                "UPDATE articles SET duplicate_of = ? WHERE url = ? AND duplicate_of IS NULL",
                (primary["id"], url),
            )
            resolved += 1
    stats["duplicates_linked"] = resolved
    stats["duplicates_dangling"] = len(pending_dupes) - resolved
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete the database first")
    args = parser.parse_args()

    if args.reset and config.DB_PATH.exists():
        config.DB_PATH.unlink()
        for suffix in ("-wal", "-shm"):
            Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
        print(f"removed {config.DB_PATH}")

    conn = db.init_db()
    conn.execute(
        "INSERT OR IGNORE INTO sources(name, tier, priority, enabled) VALUES (?,?,?,?)",
        (ADAPTER, 2, 1, 1),
    )

    for run_id, path in SOURCES:
        if not path.exists():
            print(f"skip {run_id}: {path} not found")
            continue
        already = conn.execute(
            "SELECT COUNT(*) c FROM classifications WHERE run_id = ?", (run_id,)
        ).fetchone()["c"]
        if already:
            print(f"skip {run_id}: already imported ({already} classifications). Use --reset.")
            continue
        with conn:
            stats = import_file(conn, run_id, path)
        print(f"{run_id}: " + "  ".join(f"{k}={v}" for k, v in stats.items()))

    print("\n--- totals ---")
    for table in ("articles", "classifications", "evaluations", "summaries"):
        count = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        print(f"{table:16} {count}")
    outlets = conn.execute(
        "SELECT COUNT(DISTINCT original_outlet) c FROM articles"
    ).fetchone()["c"]
    print(f"{'distinct outlets':16} {outlets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
