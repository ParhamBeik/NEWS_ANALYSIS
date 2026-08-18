#!/usr/bin/env python3
"""Re-run normalize.clean() over stored title/lead/content/outlet for existing rows.

migrations/002_rehash_content.py fixed content_hash after the html.unescape() fix in
normalize.clean() landed, so dedup matches old and new copies of the same story again -
but it never touched the displayed text itself. Rows ingested before that fix still carry
literal `&zwnj;`/`&laquo;`/`&raquo;` in original_title/lead/content/original_outlet, which
is what a reviewer, the Home feed, and the A/B diff actually render. content_hash is
unaffected here (it already folds through clean()), so this only touches display columns.

Safe to re-run: rows already clean are left untouched.

Usage:
    python migrations/003_reclean_stale_text.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_intel.core import db, normalize  # noqa: E402


def main() -> int:
    conn = db.init_db()
    rows = conn.execute(
        "SELECT id, original_title, lead, content, original_outlet FROM articles"
    ).fetchall()

    changed = 0
    with conn:
        for row in rows:
            cleaned = {
                "original_title": normalize.clean(row["original_title"]),
                "lead": normalize.clean(row["lead"] or ""),
                "content": normalize.clean(row["content"] or ""),
                "original_outlet": normalize.clean(row["original_outlet"] or ""),
            }
            if all(cleaned[k] == (row[k] or "") for k in cleaned):
                continue
            conn.execute(
                "UPDATE articles SET original_title=?, lead=?, content=?, original_outlet=?"
                " WHERE id=?",
                (*cleaned.values(), row["id"]),
            )
            changed += 1

    print(f"re-cleaned {changed} of {len(rows)} articles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
