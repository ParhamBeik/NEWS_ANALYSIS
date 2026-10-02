"""Reader-facing event projection built from the retained source articles."""

from __future__ import annotations

import math
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from articles.models import (
    Article,
    EventAlert,
    EventAssessment,
    EventRevision,
    EventWatchItem,
    GroupingDecision,
    NewsEvent,
    UrlStatus,
)
from core.actions import log_action

NOT_SAME = GroupingDecision.Decision.NOT_SAME
PRESENTATION_FIELDS = (
    "title_fa", "title_en", "brief_fa", "brief_en", "channels_fa", "channels_en",
    "uncertainty_fa", "uncertainty_en",
)


def invalidate_presentation(event: NewsEvent, reason: str) -> None:
    """Retain the old reader copy before fresh source evidence is summarized."""
    event.refresh_from_db()
    if not any(getattr(event, field) for field in PRESENTATION_FIELDS):
        return
    EventRevision.objects.create(
        event=event, reason=reason,
        **{field: getattr(event, field) for field in PRESENTATION_FIELDS},
    )
    NewsEvent.objects.filter(pk=event.pk).update(**dict.fromkeys(PRESENTATION_FIELDS, ""))


@transaction.atomic
def attach_article(article: Article) -> NewsEvent:
    """Attach copies to the canonical story without discarding article provenance."""
    canonical_id = article.duplicate_of_id or article.id
    candidates = (
        NewsEvent.objects.filter(
            Q(articles__id=canonical_id) | Q(articles__duplicate_of_id=canonical_id)
        )
        .exclude(pk__in=GroupingDecision.objects.filter(article=article, decision=NOT_SAME)
                 .values("event"))
        .distinct()
    )
    # A copy staff split out keeps its own event rather than following its canonical.
    event = candidates.filter(articles=article).first() or candidates.first()
    if event is None:
        canonical = Article.objects.get(pk=canonical_id)
        event, _ = NewsEvent.objects.get_or_create(
            primary_article=canonical,
            defaults={
                "event_time": canonical.published_at or canonical.fetched_at,
                "first_seen_at": canonical.created_at or timezone.now(),
            },
        )
        event.articles.add(canonical)
    elif event.primary_article_id != canonical_id:
        event.primary_article_id = canonical_id
        event.save(update_fields=["primary_article", "updated_at"])
    new_evidence = not event.articles.filter(pk=article.pk).exists()
    if new_evidence and event.brief_fa:
        invalidate_presentation(event, "additional_source")
        from inference.tasks import summarize_event

        transaction.on_commit(lambda event_id=event.pk: summarize_event.delay(event_id))
    event.articles.add(article)
    refresh_event(event)
    return event


def kept_apart(event_id: int) -> set[int]:
    """Events staff ruled are a different occurrence from this one, in either direction."""
    rulings = GroupingDecision.objects.filter(decision=NOT_SAME)
    against_ours = rulings.filter(article__news_events=event_id).values_list("event", flat=True)
    ours_against = NewsEvent.objects.filter(
        articles__grouping_decisions__in=rulings.filter(event_id=event_id)
    ).values_list("id", flat=True)
    return set(against_ours) | set(ours_against)


def refresh_event(event: NewsEvent) -> None:
    """Keep the timeline and correction state in sync with source observations."""
    articles = list(event.articles.all())
    if not articles:
        return
    event.event_time = min(a.published_at or a.fetched_at for a in articles)
    event.first_seen_at = min(a.created_at or a.fetched_at for a in articles)
    if all(a.url_status == UrlStatus.GONE for a in articles):
        event.status = NewsEvent.Status.WITHDRAWN
    elif any(a.revisions.exists() for a in articles):
        event.status = NewsEvent.Status.CORRECTED
    elif event.assessments.exists():
        event.status = NewsEvent.Status.ASSESSED
    event.save(update_fields=["event_time", "first_seen_at", "status", "updated_at"])


@transaction.atomic
def merge_events(target_id: int, incoming_id: int) -> NewsEvent:
    """Merge high-confidence reports while keeping each original article."""
    if target_id == incoming_id:
        return NewsEvent.objects.get(pk=target_id)
    rows = {
        row.id: row
        for row in NewsEvent.objects.select_for_update()
        .filter(pk__in=[target_id, incoming_id])
        .order_by("id")
    }
    target, incoming = rows.get(target_id), rows.get(incoming_id)
    if target is None or incoming is None:
        return target or incoming
    if target_id in kept_apart(incoming_id):
        log_action("event.merge", "refused_by_staff_split", event=target_id, incoming=incoming_id)
        return incoming
    had_presentation = bool(target.brief_fa)
    if had_presentation:
        invalidate_presentation(target, "event_merge")
    if any(getattr(incoming, field) for field in PRESENTATION_FIELDS):
        EventRevision.objects.create(
            event=target, reason="merged_event",
            **{field: getattr(incoming, field) for field in PRESENTATION_FIELDS},
        )
    for alert in EventAlert.objects.filter(event=incoming):
        retained, created = EventAlert.objects.get_or_create(
            event=target, subscription_id=alert.subscription_id,
            defaults={"sent_at": alert.sent_at, "last_error": alert.last_error},
        )
        if not created and retained.sent_at is None and alert.sent_at is not None:
            retained.sent_at = alert.sent_at
            retained.save(update_fields=["sent_at"])
    EventAssessment.objects.filter(event=incoming).update(event=target)
    for item_id in EventWatchItem.objects.filter(event=incoming).values_list("item", flat=True):
        EventWatchItem.objects.get_or_create(event=target, item_id=item_id)
    # A ruling against the absorbed event now holds against the event that absorbed it.
    for ruling in GroupingDecision.objects.filter(event=incoming):
        GroupingDecision.objects.get_or_create(
            article_id=ruling.article_id, event=target,
            defaults={"decision": ruling.decision, "decided_by_id": ruling.decided_by_id},
        )
    target.articles.add(*incoming.articles.all())
    incoming.delete()
    refresh_event(target)
    if had_presentation:
        from inference.tasks import summarize_event

        transaction.on_commit(lambda event_id=target.pk: summarize_event.delay(event_id))
    return target


@transaction.atomic
def split_article_from_event(event_id: int, article_id: int, user=None) -> NewsEvent:
    """Undo a wrong grouping: move one report, with its own copies, into a new event.

    The remaining event keeps its assessments and review; the new one is unassessed and
    queued for Jev like any fresh story. The ruling is stored so grouping never re-merges
    the two.
    """
    event = NewsEvent.objects.select_for_update().get(pk=event_id)
    members = list(event.articles.all())
    moving = [a for a in members if article_id in (a.id, a.duplicate_of_id)]
    article = next((a for a in moving if a.id == article_id), None)
    if article is None:
        raise ValueError("article is not part of this event")
    remaining = [a for a in members if a not in moving]
    if not remaining:
        raise ValueError("an event's only report cannot be split out")
    primary_changed = event.primary_article_id in {a.id for a in moving}
    if primary_changed:
        # OneToOne: the old event must let go of the article before the new one takes it.
        event.primary_article = min(
            remaining, key=lambda a: (a.published_at or a.fetched_at, a.id)
        )
        event.save(update_fields=["primary_article", "updated_at"])
    event.articles.remove(*moving)
    split = NewsEvent.objects.create(
        primary_article=article,
        event_time=article.published_at or article.fetched_at,
        first_seen_at=article.created_at or timezone.now(),
    )
    split.articles.add(*moving)
    GroupingDecision.objects.update_or_create(
        article=article, event=event,
        defaults={"decision": NOT_SAME, "decided_by": user},
    )
    refresh_event(split)
    refresh_event(event)
    had_presentation = bool(event.brief_fa)
    if had_presentation:
        invalidate_presentation(event, "event_split")
    from inference.tasks import assess_event, summarize_event

    transaction.on_commit(lambda event_id=split.pk: assess_event.delay(event_id))
    if primary_changed:
        transaction.on_commit(lambda event_id=event.pk: assess_event.delay(event_id))
    elif had_presentation:
        transaction.on_commit(lambda event_id=event.pk: summarize_event.delay(event_id))
    log_action("event.split", "split", event=event.pk, article=article_id, new_event=split.pk)
    return split


def ranked_events(queryset, now=None):
    """Small bounded page ranking; score is separate from model confidence."""
    now = now or timezone.now()
    events = list(queryset)
    return sorted(
        events,
        key=lambda event: (
            (0.6 * (event.iran_score or 0) + 0.4 * (event.global_score or 0))
            * 0.5 ** (max(0, (now - event.event_time).total_seconds()) / (12 * 3600)),
            event.event_time,
        ),
        reverse=True,
    )


def priority_visibility(window_days: int = 14) -> dict:
    """Observed source-publication to event-ingest latency for priority articles."""
    now = timezone.now()
    rows = Article.objects.filter(
        source__tier=1,
        published_at__gte=now - timedelta(days=window_days),
        date_uncertain=False,
    ).values_list("published_at", "created_at")
    delays = sorted(
        max(0, (seen - published).total_seconds() / 60)
        for published, seen in rows.iterator()
        if seen >= published and seen <= now
    )
    if not delays:
        return {"sample_size": 0, "p95_minutes": None, "within_10_minutes": None}
    return {
        "sample_size": len(delays),
        "p95_minutes": round(delays[math.ceil(len(delays) * 0.95) - 1], 2),
        "within_10_minutes": round(sum(delay <= 10 for delay in delays) / len(delays), 3),
    }
