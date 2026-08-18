#!/usr/bin/env python3
"""Recompute content_hash for existing rows after the html.unescape() fix in normalize.clean().

Rows ingested before that fix have a content_hash computed over entity-laden text
(`&zwnj;` etc). A duplicate of the same story re-crawled after the fix hashes differently
under the unescaped text, so dedupe's exact content_hash match silently misses it. This
recomputes content_hash (and identity_key, which is derived from it) from the stored
title/lead/content for every row, so old and new copies of the same story collide again.

Safe to re-run: rows whose hash already matches the current normalize.content_hash are
left untouched.

Usage:
    python migrations/002_rehash_content.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_intel.core import db, normalize  # noqa: E402


def main() -> int:
    conn = db.init_db()
    rows = conn.execute(
        "SELECT id, original_title, lead, content, content_hash FROM articles"
    ).fetchall()

    changed = 0
    with conn:
        for row in rows:
            new_hash = normalize.content_hash(row["original_title"], row["lead"], row["content"])
            if new_hash == row["content_hash"]:
                continue
            conn.execute(
                "UPDATE articles SET content_hash = ?, identity_key = ? WHERE id = ?",
                (new_hash, f"hash:{new_hash}", row["id"]),
            )
            changed += 1

    print(f"rehashed {changed} of {len(rows)} articles")
    print("run `python -m news_intel.cli dedupe --apply` next to link any duplicates the old hashes missed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
