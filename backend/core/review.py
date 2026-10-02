"""Swipe review of Jev's event judgments: queue order, decisions, and agreement.

Scores are 0-100 but Jev answers on a 0-4 scale (stored as x25), so a reviewer judges the
same five levels the model chose between. Agreement is measured on levels, not raw scores.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.db.models import Case, Exists, F, IntegerField, OuterRef, Value, When
from django.utils import timezone

from articles.models import EventReview, EventRevision
from core.tiers import band
from core.vocabulary import EVENT_CATEGORIES, LEVELS, event_topic

SESSION_SIZE = 25
HIGH_IMPACT_UNCERTAIN = "high_impact_uncertain"
# `merge_events` records these revisions; they are the only durable merge trail.
MERGE_REASONS = ("event_merge", "merged_event")
RECENT_MERGE = timedelta(days=7)
ACTIONS = ("agree", "fix", "skip", "undo")


def score_tier(score: int | None) -> int | None:
    """0-100 score to the reviewer's level index 0-4 (LEVELS order); None stays None.

    The fixed band from core.tiers, minus one. Agreement must not use the relative reader
    tier: its cut-offs move with the month, which would rewrite past agreement rates.
    """
    tier = band(score)
    return None if tier is None else tier - 1


def tier_score(tier: int) -> int:
    return tier * 25


def review_queue(now=None):
    """Pending reviews, most informative first.

    Unskipped before skipped; high-impact-uncertain before audit samples; then lowest model
    confidence; then events merged in the last week (a merge is a grouping decision worth
    checking); then oldest first.
    """
    now = now or timezone.now()
    merged = EventRevision.objects.filter(
        event=OuterRef("event"), reason__in=MERGE_REASONS, observed_at__gte=now - RECENT_MERGE
    )
    return (
        EventReview.objects.filter(
            status=EventReview.Status.PENDING,
            event__category__gt="",
            event__iran_score__isnull=False,
            event__global_score__isnull=False,
        )
        .annotate(
            recently_merged=Exists(merged),
            uncertain_first=Case(
                When(reason=HIGH_IMPACT_UNCERTAIN, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        )
        .order_by(
            F("skipped_at").asc(nulls_first=True),
            "uncertain_first",
            F("event__assessment_confidence").asc(nulls_last=True),
            F("recently_merged").desc(),
            "created_at",
            "id",
        )
    )


def _tier(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(LEVELS):
        raise ValueError(f"{name} must be a tier from 0 to {len(LEVELS) - 1}")
    return value


def record_decision(
    review: EventReview,
    user,
    action: str,
    *,
    category: str | None = None,
    iran_tier: int | None = None,
    global_tier: int | None = None,
    now=None,
) -> EventReview:
    """Apply one reviewer action. `agree` copies the model's current judgment verbatim."""
    now = now or timezone.now()
    event = review.event
    if action == "agree":
        if not event.category or event.iran_score is None or event.global_score is None:
            raise ValueError("event has no complete model judgment to agree with")
        values = (event.category, event.iran_score, event.global_score)
    elif action == "fix":
        if category not in EVENT_CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(EVENT_CATEGORIES)}")
        values = (
            category,
            tier_score(_tier(iran_tier, "iran_tier")),
            tier_score(_tier(global_tier, "global_tier")),
        )
    elif action == "skip":
        review.skipped_at = now
        review.save(update_fields=["skipped_at"])
        return review
    elif action == "undo":
        review.status = EventReview.Status.PENDING
        review.reviewed_category = ""
        review.reviewed_iran_score = review.reviewed_global_score = None
        review.reviewer = review.reviewed_at = review.skipped_at = None
        review.save()
        return review
    else:
        raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
    (
        review.reviewed_category,
        review.reviewed_iran_score,
        review.reviewed_global_score,
    ) = values
    review.status = EventReview.Status.REVIEWED
    review.reviewer = user
    review.reviewed_at = now
    review.save()
    return review


def _model_judgment(review: EventReview) -> tuple[str, int | None, int | None]:
    """What Jev had decided when the human looked: the latest assessment at review time.

    The event's own fields move on a reassessment, so comparing against them would let a
    later model answer rewrite an earlier agreement rate.
    """
    shown = [a for a in review.event.assessments.all() if a.created_at <= review.reviewed_at]
    latest = max(shown, key=lambda a: a.id, default=None)
    if latest is None:
        event = review.event
        return event.category, event.iran_score, event.global_score
    return latest.category, latest.iran_score, latest.global_score


def review_stats(*, since=None, reviewer=None) -> dict:
    """Agreement between reviewers and Jev, overall and per model category.

    An item agrees when the category and both impact tiers match.
    """
    rows = EventReview.objects.filter(
        status=EventReview.Status.REVIEWED,
        reviewed_at__isnull=False,
        reviewed_iran_score__isnull=False,
        reviewed_global_score__isnull=False,
    ).select_related("event").prefetch_related("event__assessments")
    if since is not None:
        rows = rows.filter(reviewed_at__gte=since)
    if reviewer is not None:
        rows = rows.filter(reviewer=reviewer)
    per_category = defaultdict(lambda: {"reviewed": 0, "agreed": 0, "category": 0, "tier": 0})
    for row in rows:
        category, iran, global_ = _model_judgment(row)
        # Older rows hold the pre-investor-topic slugs; compare in today's vocabulary.
        category = event_topic(category)
        category_ok = category == event_topic(row.reviewed_category)
        tier_ok = score_tier(iran) == score_tier(row.reviewed_iran_score) and score_tier(
            global_
        ) == score_tier(row.reviewed_global_score)
        bucket = per_category[category or "unassessed"]
        bucket["reviewed"] += 1
        bucket["agreed"] += category_ok and tier_ok
        bucket["category"] += category_ok
        bucket["tier"] += tier_ok
    reviewed = sum(b["reviewed"] for b in per_category.values())
    agreed = sum(b["agreed"] for b in per_category.values())
    return {
        "reviewed": reviewed,
        "agreed": agreed,
        "agreement_rate": round(agreed / reviewed, 3) if reviewed else None,
        "categories": [
            {
                "category": name,
                "reviewed": b["reviewed"],
                "agreement_rate": round(b["agreed"] / b["reviewed"], 3),
                "category_match_rate": round(b["category"] / b["reviewed"], 3),
                "tier_match_rate": round(b["tier"] / b["reviewed"], 3),
            }
            for name, b in sorted(per_category.items(), key=lambda item: -item[1]["reviewed"])
        ],
    }
