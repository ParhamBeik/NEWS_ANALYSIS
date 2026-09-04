"""Cross-source deduplication: exact content hash, then trigram Jaccard over folded titles.

FROZEN INVARIANT (1/4). THRESHOLD is measured, not guessed. Sweeping every title pair in
the production corpus: J 0.50-0.70 is mostly false positives (Persian news runs
date-templated titles, so two different horoscopes score 0.62); J >= 0.70 gives 44 pairs,
43 of them true duplicates; the one false positive sits at 0.704, two different cities
sharing the بندر stem.

0.75 rather than 0.70 because the errors are NOT equally costly. A false positive silently
drops a real story from the analyst's workbook; a false negative just prints a duplicate
row. So it buys precision with recall, giving up ~5 of 44 real duplicates. Reworded
duplicates below the threshold are knowingly out of reach - the embeddings this system now
computes are the upgrade path if that recall ever matters.

Exact hash matches bypass the threshold: they are identity, not similarity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Q

from core.text import jaccard, trigrams

THRESHOLD = 0.75
WINDOW_HOURS = 36
UNDATED_CANDIDATE_LIMIT = 300  # fallback pool for articles with no parseable date
DEFAULT_PRIORITY = 50


@dataclass(frozen=True)
class Match:
    article_id: int
    score: float
    reason: str


def candidates(article):
    """Canonical articles near this one in time.

    Time-window blocking is what keeps this from an O(n^2) corpus scan. No LSH banding: a
    36h window holds a few hundred rows and the comparison is set intersection. Add banding
    only if a window ever exceeds a few thousand.

    Undated articles (Shahrekhabar produces them routinely) fall back to the most recently
    ingested rows rather than returning nothing, which used to skip them past dedup
    entirely; ingest order is a serviceable proxy for publication time.
    """
    from .models import Article

    base = (
        Article.objects.canonical()
        .exclude(pk=article.pk)
        .exclude(original_title="")
        # Titles only. `find_duplicate` reads nothing else off these rows, and `content` is
        # the full article body: loading it for every candidate moved megabytes per article
        # across the connection to compute a trigram set over the headline. The nightly
        # `backfill_dedupe` sweep runs this once per stored article, so the waste multiplied
        # by the size of the corpus. `link()` re-fetches the one row that actually matched.
        .only("id", "original_title")
    )
    if article.published_at is None:
        return base.order_by("-id")[:UNDATED_CANDIDATE_LIMIT]
    span = timedelta(hours=WINDOW_HOURS)
    return base.filter(
        published_at__range=(article.published_at - span, article.published_at + span)
    )


def find_duplicate(article) -> Match | None:
    """The canonical article this one duplicates, if any."""
    from .models import Article

    exact = (
        Article.objects.canonical()
        .filter(content_hash=article.content_hash)
        .exclude(pk=article.pk)
        .order_by("id")
        .values_list("id", flat=True)
        .first()
    )
    if exact:
        return Match(exact, 1.0, "content_hash")

    terms = trigrams(article.original_title)
    if not terms:
        return None
    best: Match | None = None
    for other in candidates(article).iterator():
        score = jaccard(terms, trigrams(other.original_title))
        if score >= THRESHOLD and (best is None or score > best.score):
            best = Match(other.pk, score, "title_similarity")
    return best


def _priority(article) -> int:
    return article.source.priority if article.source_id else DEFAULT_PRIORITY


def better_canonical(left, right) -> bool:
    """True when `left` is the better copy to keep: existing inference first, then source
    priority, then more content.

    An already-classified article - possibly paid for - must never be demoted in favour of
    an unclassified duplicate. Doing so detaches the inference from the surviving id and
    lets a later, cheaper run silently replace a real result with a cruder one. Content
    length is the next tiebreak that matters: Shahrekhabar listings often carry an empty
    body.
    """
    from inference.models import Classification

    def classified(article) -> bool:
        return Classification.objects.filter(article_id=article.pk).exists()

    left_classified, right_classified = classified(left), classified(right)
    if left_classified != right_classified:
        return left_classified
    left_rank, right_rank = _priority(left), _priority(right)
    if left_rank != right_rank:
        return left_rank < right_rank
    return len(left.content or "") > len(right.content or "")


def link(article, match: Match) -> int:
    """Point the weaker copy at the stronger one; return the surviving canonical id.

    If the new article is the better copy, the existing canonical is demoted and everything
    pointing at it is repointed - so the chain never grows past one level and
    `duplicate_of IS NULL` stays a reliable "this is the story" filter.
    """
    from .models import Article

    incumbent = Article.objects.filter(pk=match.article_id).first()
    if incumbent is None:
        return article.pk

    if not better_canonical(article, incumbent):
        Article.objects.filter(pk=article.pk).update(
            duplicate_of=incumbent, duplicate_score=match.score, duplicate_reason=match.reason
        )
        return incumbent.pk

    Article.objects.filter(duplicate_of=incumbent).update(duplicate_of=article)
    Article.objects.filter(pk=incumbent.pk).update(
        duplicate_of=article, duplicate_score=match.score, duplicate_reason=match.reason
    )
    Article.objects.filter(pk=article.pk).update(
        duplicate_of=None, duplicate_score=None, duplicate_reason=""
    )
    return article.pk


def resolve(article) -> Match | None:
    """Find and link a duplicate in one step. Returns the match, or None if unique."""
    match = find_duplicate(article)
    if match is not None:
        link(article, match)
        article.refresh_from_db(fields=["duplicate_of", "duplicate_score", "duplicate_reason"])
    return match


def backfill(
    *, dry_run: bool = False, since: datetime | None = None
) -> list[tuple[str, str, float]]:
    """Apply near-duplicate detection to articles already stored.

    The imported legacy corpus was deduplicated by URL alone, so reworded republications
    are still separate rows. Returns (title, other title, score) per merged pair.
    """
    from .models import Article

    rows = Article.objects.canonical().exclude(original_title="").order_by("published_at")
    if since is not None:
        rows = rows.filter(Q(published_at__gte=since) | Q(published_at__isnull=True))

    merged: list[tuple[str, str, float]] = []
    # In dry-run nothing is linked, so without this the same pair reports twice - once from
    # each side - and the count comes out double.
    claimed: set[int] = set()
    for article in rows.iterator():
        if article.pk in claimed:
            continue
        current = Article.objects.filter(pk=article.pk).values_list("duplicate_of", flat=True)
        if not current or current[0] is not None:
            continue
        match = find_duplicate(article)
        if match is None:
            continue
        other_title = (
            Article.objects.filter(pk=match.article_id)
            .values_list("original_title", flat=True)
            .first()
            or ""
        )
        merged.append((article.original_title, other_title, match.score))
        claimed.update({article.pk, match.article_id})
        if not dry_run:
            link(article, match)
    return merged
