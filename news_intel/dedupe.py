"""Cross-source deduplication.

Three sources publish the same story, and Khabarfoori is itself an aggregator that
republishes Mehr, so crawling Mehr directly meets the same article twice. Without this,
one story becomes three rows in the analyst's workbook and gets classified three times.

Two tiers:

1. Exact - identical `content_hash`. Folded normalization means encoding variants of the
   same text collide (see core/normalize.py).
2. Near  - character-trigram Jaccard over folded titles, within a time window.

THRESHOLD is measured, not guessed. Sweeping every title pair in the production corpus
inside the time window:

    J 0.50-0.70 mostly FALSE positives - Persian news runs date-templated titles, so
                "فال قهوه سه شنبه ۱ اردیبهشت" and "فال روزانه سه شنبه ۱ اردیبهشت" score
                0.62 while being different articles
    J >= 0.70   44 pairs, 43 of them true duplicates (punctuation, "/ عکس" suffixes,
                "فوری/" prefixes, outlet attribution moved into the headline)
    J 0.704     the one false positive, and it is instructive:
                  "انفجارهای کنترل شده در شرق شهر بندرعباس"
                  "انفجارهای کنترل شده در بندرلنگه"
                Two different cities. Trigrams cannot separate place-name substitutions
                because بندرعباس and بندرلنگه share the بندر stem.

Set at 0.75 rather than 0.70 because the two errors are not equally costly. A false
positive merges two real stories and one of them silently disappears from the analyst's
workbook - the same class of invisible suppression that made the legacy pipeline drop
every security alert. A false negative just prints a duplicate row, which is visible and
harmless. So the threshold buys precision with recall: it gives up ~5 of the 44 real
duplicates to eliminate the known false-positive class.

Exact content_hash matches bypass the threshold entirely; they are not similarity
judgements. Reworded duplicates below 0.75 are knowingly out of reach - catching them
with trigrams would also merge every horoscope published on the same day. Embeddings are
the upgrade path if that recall ever matters; it does not today.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from .core import normalize

THRESHOLD = 0.75
WINDOW_HOURS = 36
# Fallback pool for articles with no parseable publish date.
UNDATED_CANDIDATE_LIMIT = 300

# Which source's copy to keep when the same story arrives from several. Lower wins.
# Khabarfoori carries full article bodies; Shahrekhabar's listing often carries none.
DEFAULT_PRIORITY = 50


@dataclass(frozen=True)
class Match:
    article_id: int
    score: float
    reason: str


def _window(published_at: str | None) -> tuple[str, str] | None:
    """ISO strings compare lexicographically, so a string BETWEEN is a valid time window."""
    if not published_at:
        return None
    try:
        moment = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    span = timedelta(hours=WINDOW_HOURS)
    return (moment - span).isoformat(), (moment + span).isoformat()


def candidates(
    conn: sqlite3.Connection, *, article_id: int, published_at: str | None
) -> list[sqlite3.Row]:
    """Canonical articles near this one in time.

    Time-window blocking is what keeps this from being an O(n^2) scan of the whole
    corpus. ponytail: no LSH banding - a 36h window holds a few hundred rows and the
    comparison is set intersection. Add banding if a window ever exceeds a few thousand.

    Articles with no usable publish date used to return no candidates at all, which meant
    they silently skipped near-duplicate detection entirely. Shahrekhabar produces
    undated entries routinely, so those duplicates were going straight through. They now
    fall back to the most recently ingested rows - the window is what bounds cost, and
    ingest order is a serviceable proxy for publication time.
    """
    window = _window(published_at)
    if window is None:
        return conn.execute(
            "SELECT id, original_title, source, content FROM articles"
            " WHERE duplicate_of IS NULL AND id != ? AND original_title != ''"
            " ORDER BY id DESC LIMIT ?",
            (article_id, UNDATED_CANDIDATE_LIMIT),
        ).fetchall()
    return conn.execute(
        "SELECT id, original_title, source, content FROM articles"
        " WHERE duplicate_of IS NULL AND id != ?"
        "   AND published_at_gregorian BETWEEN ? AND ?"
        "   AND original_title != ''",
        (article_id, *window),
    ).fetchall()


def find_duplicate(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    title: str,
    content_hash: str,
    published_at: str | None,
) -> Match | None:
    """Return the canonical article this one duplicates, if any."""
    exact = conn.execute(
        "SELECT id FROM articles WHERE content_hash = ? AND duplicate_of IS NULL"
        " AND id != ? ORDER BY id LIMIT 1",
        (content_hash, article_id),
    ).fetchone()
    if exact:
        return Match(int(exact["id"]), 1.0, "content_hash")

    terms = normalize.trigrams(title)
    if not terms:
        return None

    best: Match | None = None
    for row in candidates(conn, article_id=article_id, published_at=published_at):
        score = normalize.jaccard(terms, normalize.trigrams(row["original_title"]))
        if score >= THRESHOLD and (best is None or score > best.score):
            best = Match(int(row["id"]), score, "title_similarity")
    return best


def source_priority(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT priority FROM sources WHERE name = ?", (name,)).fetchone()
    return int(row["priority"]) if row else DEFAULT_PRIORITY


def _better_canonical(conn: sqlite3.Connection, left: sqlite3.Row, right: sqlite3.Row) -> bool:
    """True when `left` is the better copy to keep: source priority, then more content.

    Content length is the tiebreak that matters in practice - Shahrekhabar's listing
    entries frequently carry an empty body, and making one canonical would leave the
    workbook row with nothing to summarize.
    """
    left_rank = source_priority(conn, left["source"])
    right_rank = source_priority(conn, right["source"])
    if left_rank != right_rank:
        return left_rank < right_rank
    return len(left["content"] or "") > len(right["content"] or "")


def link(conn: sqlite3.Connection, *, article_id: int, match: Match) -> int:
    """Point the weaker copy at the stronger one and return the canonical id.

    If the newly arrived article is the better copy, the existing canonical is demoted
    and anything already pointing at it is repointed, so the chain never grows past one
    level and `duplicate_of IS NULL` stays a reliable "this is the story" filter.
    """
    new = conn.execute(
        "SELECT id, source, content FROM articles WHERE id = ?", (article_id,)
    ).fetchone()
    old = conn.execute(
        "SELECT id, source, content FROM articles WHERE id = ?", (match.article_id,)
    ).fetchone()
    if new is None or old is None:
        return match.article_id

    if _better_canonical(conn, new, old):
        conn.execute("UPDATE articles SET duplicate_of = ? WHERE duplicate_of = ?",
                     (article_id, match.article_id))
        conn.execute("UPDATE articles SET duplicate_of = ? WHERE id = ?",
                     (article_id, match.article_id))
        conn.execute("UPDATE articles SET duplicate_of = NULL WHERE id = ?", (article_id,))
        return article_id

    conn.execute("UPDATE articles SET duplicate_of = ? WHERE id = ?",
                 (match.article_id, article_id))
    return match.article_id


def backfill(conn: sqlite3.Connection, *, dry_run: bool = False) -> list[tuple[str, str, float]]:
    """Apply near-duplicate detection to articles already stored.

    Ingest-time dedup only sees articles that arrive after it exists. The corpus imported
    from the legacy JSON was deduplicated by URL identity alone, so reworded republications
    are still sitting in it as separate rows.
    """
    rows = conn.execute(
        "SELECT id, original_title, content_hash, published_at_gregorian FROM articles"
        " WHERE duplicate_of IS NULL AND original_title != ''"
        " ORDER BY published_at_gregorian"
    ).fetchall()
    merged: list[tuple[str, str, float]] = []
    # In dry-run nothing is linked, so without this the same pair is reported twice, once
    # from each side, and the count comes out double.
    claimed: set[int] = set()
    for row in rows:
        if int(row["id"]) in claimed:
            continue
        still_canonical = conn.execute(
            "SELECT duplicate_of FROM articles WHERE id = ?", (row["id"],)
        ).fetchone()
        if still_canonical is None or still_canonical["duplicate_of"] is not None:
            continue
        match = find_duplicate(
            conn,
            article_id=int(row["id"]),
            title=row["original_title"],
            content_hash=row["content_hash"],
            published_at=row["published_at_gregorian"],
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


def resolve(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    title: str,
    content_hash: str,
    published_at: str | None,
) -> Match | None:
    """Find and link a duplicate in one step. Returns the match, or None if unique."""
    match = find_duplicate(
        conn,
        article_id=article_id,
        title=title,
        content_hash=content_hash,
        published_at=published_at,
    )
    if match is not None:
        link(conn, article_id=article_id, match=match)
    return match
