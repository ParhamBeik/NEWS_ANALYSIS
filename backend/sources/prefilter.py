"""Cost prefilter: which articles are stored but not paid for.

Deliberately narrow. It matches ONE field - the newsroom's own taxonomy slug, scoped to
the source that emitted it - against an explicit list of desks. It does not read the
article text, does not guess, and has no default-deny branch: an article whose source
publishes no slug is always eligible for inference.

That narrowness is the safety property. A prefilter that inferred irrelevance from article
text would be a second, unmeasured classifier sitting in front of the real one, deciding
what the real one never gets to see.

`observed_slugs` is the other half of the design: you switch a rule on because the data
says that desk produces only `other`, not because the slug sounds unimportant. Provincial
desks are the trap - Iranian border incidents are filed under a province, so "it's just
local news" is exactly the assumption that would drop a security story.
"""

from __future__ import annotations

from functools import lru_cache

from .models import PrefilterRule


@lru_cache(maxsize=1)
def _enabled_rules() -> frozenset[tuple[str | None, str]]:
    """(source_id, slug) pairs currently suppressing spend. None means every source."""
    return frozenset(
        (source_id, slug.lower())
        for source_id, slug in PrefilterRule.objects.filter(enabled=True).values_list(
            "source_id", "native_category"
        )
    )


def reload_rules() -> None:
    """Call after editing rules; the crawl path reads this on every article."""
    _enabled_rules.cache_clear()


def reason_for(source_name: str, native_category: str) -> str:
    """The prefilter reason for this article, or '' when it should be inferred."""
    slug = (native_category or "").strip().lower()
    if not slug:
        return ""
    rules = _enabled_rules()
    if (source_name, slug) in rules or (None, slug) in rules:
        return f"native_category:{slug}"
    return ""


def reapply(queryset=None) -> dict[str, int]:
    """Re-evaluate stored articles against the current rules.

    Both directions matter. Enabling a rule holds back articles not yet inferred; DISABLING
    one has to actually release the articles it was suppressing, or the switch is a lie and
    the corpus stays quietly truncated.
    """
    from articles.models import Article

    reload_rules()
    articles = queryset if queryset is not None else Article.objects.all()
    held, released = 0, 0
    rows = articles.only("id", "source_id", "native_category", "prefilter_reason")
    for article in rows.iterator():
        wanted = reason_for(article.source_id, article.native_category)
        if wanted == article.prefilter_reason:
            continue
        Article.objects.filter(pk=article.pk).update(prefilter_reason=wanted)
        held, released = (held + 1, released) if wanted else (held, released + 1)
    return {"held": held, "released": released}


def observed_slugs(min_articles: int = 5) -> list[dict]:
    """Evidence for switching a rule on: per (source, slug), how many articles and what
    the classifier actually decided about them.

    A slug worth suppressing is one with enough volume to matter and an `other` share at or
    near 100%. Anything below that is a desk that occasionally files something real, and
    suppressing it trades money for a story.
    """
    from django.db.models import Count, Q

    from articles.models import Article
    from inference.models import Classification

    latest = Classification.objects.latest_ids()
    rows = (
        Article.objects.exclude(native_category="")
        .values("source_id", "native_category")
        .annotate(
            articles=Count("id", distinct=True),
            classified=Count(
                "classifications", filter=Q(classifications__in=latest), distinct=True
            ),
            other=Count(
                "classifications",
                filter=Q(classifications__in=latest, classifications__category="other"),
                distinct=True,
            ),
        )
        .filter(articles__gte=min_articles)
        .order_by("-articles")
    )
    return [
        {
            **row,
            "other_share": (row["other"] / row["classified"]) if row["classified"] else None,
            "enabled": (row["source_id"], row["native_category"].lower()) in _enabled_rules(),
        }
        for row in rows
    ]
