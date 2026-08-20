"""Cross-source deduplication: exact content hash, then trigram Jaccard over folded titles.

THRESHOLD is measured, not guessed. Sweeping every title pair in the production corpus:
J 0.50-0.70 is mostly false positives (Persian news runs date-templated titles, so two
different horoscopes score 0.62); J >= 0.70 gives 44 pairs, 43 of them true duplicates;
the one false positive sits at 0.704, two different cities sharing the بندر stem.

0.75 rather than 0.70 because the errors are not equally costly: a false positive silently
drops a real story from the analyst's workbook, a false negative just prints a duplicate
row. So it buys precision with recall, giving up ~5 of 44 real duplicates. Reworded
duplicates below the threshold are knowingly out of reach; embeddings are the upgrade path
if that recall ever matters. Exact hash matches bypass the threshold - they are identity,
not similarity.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from . import text

THRESHOLD = 0.75
WINDOW_HOURS = 36
UNDATED_CANDIDATE_LIMIT = 300  # fallback pool for articles with no parseable date
DEFAULT_PRIORITY = 50

_CANDIDATE_COLUMNS = "id, original_title, source, content"


@dataclass(frozen=True)
class Match:
    article_id: int
    score: float
    reason: str


def candidates(conn: sqlite3.Connection, *, article_id: int, published_at: str | None) -> list[sqlite3.Row]:
    """Canonical articles near this one in time.

    Time-window blocking is what keeps this from being an O(n^2) corpus scan. ponytail: no
    LSH banding - a 36h window holds a few hundred rows and the comparison is set
    intersection. Add banding if a window ever exceeds a few thousand.

    Undated articles (Shahrekhabar produces them routinely) fall back to the most recently
    ingested rows rather than returning nothing, which used to skip them past dedup
    entirely; ingest order is a serviceable proxy for publication time.
    """
    moment = text.parse_iso(published_at)
    if moment is None:
        return conn.execute(
            f"SELECT {_CANDIDATE_COLUMNS} FROM articles"
            " WHERE duplicate_of IS NULL AND id != ? AND original_title != ''"
            " ORDER BY id DESC LIMIT ?",
            (article_id, UNDATED_CANDIDATE_LIMIT),
        ).fetchall()
    # ISO strings compare lexicographically, so a string BETWEEN is a valid time window.
    span = timedelta(hours=WINDOW_HOURS)
    return conn.execute(
        f"SELECT {_CANDIDATE_COLUMNS} FROM articles"
        " WHERE duplicate_of IS NULL AND id != ?"
        "   AND published_at_gregorian BETWEEN ? AND ? AND original_title != ''",
        (article_id, (moment - span).isoformat(), (moment + span).isoformat()),
    ).fetchall()


def find_duplicate(
    conn: sqlite3.Connection, *, article_id: int, title: str, content_hash: str, published_at: str | None
) -> Match | None:
    """Return the canonical article this one duplicates, if any."""
    exact = conn.execute(
        "SELECT id FROM articles WHERE content_hash = ? AND duplicate_of IS NULL AND id != ?"
        " ORDER BY id LIMIT 1",
        (content_hash, article_id),
    ).fetchone()
    if exact:
        return Match(int(exact["id"]), 1.0, "content_hash")

    terms = text.trigrams(title)
    if not terms:
        return None
    best: Match | None = None
    for row in candidates(conn, article_id=article_id, published_at=published_at):
        score = text.jaccard(terms, text.trigrams(row["original_title"]))
        if score >= THRESHOLD and (best is None or score > best.score):
            best = Match(int(row["id"]), score, "title_similarity")
    return best


def _better_canonical(conn: sqlite3.Connection, left: sqlite3.Row, right: sqlite3.Row) -> bool:
    """True when `left` is the better copy to keep: existing inference first, then source
    priority, then more content.

    An already-classified article - possibly by a paid provider - must never be demoted in
    favour of an unclassified duplicate, because that detaches the inference from the
    surviving id and lets a later run (backfill always uses the free rule provider)
    silently replace a real result with a cruder one. Content length is the next tiebreak
    that matters: Shahrekhabar listings often carry an empty body.
    """
    def classified(row: sqlite3.Row) -> bool:
        return bool(conn.execute(
            "SELECT 1 FROM classifications WHERE article_id = ? LIMIT 1", (row["id"],)
        ).fetchone())

    def priority(row: sqlite3.Row) -> int:
        found = conn.execute(
            "SELECT priority FROM sources WHERE name = ?", (row["source"],)
        ).fetchone()
        return int(found["priority"]) if found else DEFAULT_PRIORITY

    left_classified, right_classified = classified(left), classified(right)
    if left_classified != right_classified:
        return left_classified
    left_rank, right_rank = priority(left), priority(right)
    if left_rank != right_rank:
        return left_rank < right_rank
    return len(left["content"] or "") > len(right["content"] or "")


def link(conn: sqlite3.Connection, *, article_id: int, match: Match) -> int:
    """Point the weaker copy at the stronger one and return the canonical id.

    If the new article is the better copy the existing canonical is demoted and anything
    pointing at it is repointed, so the chain never grows past one level and
    `duplicate_of IS NULL` stays a reliable "this is the story" filter.
    """
    def row(identifier: int) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT id, source, content FROM articles WHERE id = ?", (identifier,)
        ).fetchone()

    new, old = row(article_id), row(match.article_id)
    if new is None or old is None:
        return match.article_id
    if not _better_canonical(conn, new, old):
        conn.execute("UPDATE articles SET duplicate_of = ? WHERE id = ?", (match.article_id, article_id))
        return match.article_id
    conn.execute("UPDATE articles SET duplicate_of = ? WHERE duplicate_of = ?", (article_id, match.article_id))
    conn.execute("UPDATE articles SET duplicate_of = ? WHERE id = ?", (article_id, match.article_id))
    conn.execute("UPDATE articles SET duplicate_of = NULL WHERE id = ?", (article_id,))
    return article_id


def resolve(
    conn: sqlite3.Connection, *, article_id: int, title: str, content_hash: str, published_at: str | None
) -> Match | None:
    """Find and link a duplicate in one step. Returns the match, or None if unique."""
    match = find_duplicate(
        conn, article_id=article_id, title=title, content_hash=content_hash, published_at=published_at
    )
    if match is not None:
        link(conn, article_id=article_id, match=match)
    return match


def backfill(conn: sqlite3.Connection, *, dry_run: bool = False) -> list[tuple[str, str, float]]:
    """Apply near-duplicate detection to articles already stored - the imported legacy
    corpus was deduplicated by URL alone, so reworded republications are still separate
    rows. Returns (title, other title, score) per merged pair."""
    rows = conn.execute(
        "SELECT id, original_title, content_hash, published_at_gregorian FROM articles"
        " WHERE duplicate_of IS NULL AND original_title != '' ORDER BY published_at_gregorian"
    ).fetchall()
    merged: list[tuple[str, str, float]] = []
    # In dry-run nothing is linked, so without this the same pair reports twice, once from
    # each side, and the count comes out double.
    claimed: set[int] = set()
    for row in rows:
        if int(row["id"]) in claimed:
            continue
        current = conn.execute("SELECT duplicate_of FROM articles WHERE id = ?", (row["id"],)).fetchone()
        if current is None or current["duplicate_of"] is not None:
            continue
        match = find_duplicate(
            conn, article_id=int(row["id"]), title=row["original_title"],
            content_hash=row["content_hash"], published_at=row["published_at_gregorian"],
        )
        if match is None:
            continue
        other = conn.execute(
            "SELECT original_title FROM articles WHERE id = ?", (match.article_id,)
        ).fetchone()
        merged.append((row["original_title"], other["original_title"], match.score))
        claimed.update({int(row["id"]), match.article_id})
        if not dry_run:
            link(conn, article_id=int(row["id"]), match=match)
    return merged
