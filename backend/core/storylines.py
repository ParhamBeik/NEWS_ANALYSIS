"""Storylines: link recent events into developing situations, cheaply, once a day.

No model call decides membership. Two events are linked when their primary articles'
embeddings are close (pgvector cosine), or moderately close and sharing a watch item, or,
without embeddings, when they share two watch items and the same topic. Embeddings are
optional (`embed_missing` is off by default), so the watch-item rule is what runs today;
the cosine rules take over as embeddings appear.

Each new event joins the storyline of its best-linked recent event, or starts one with a
linked event that has none. An event belongs to at most one storyline. Only naming may
call a model, and naming failure keeps the previous name (or one derived from the first
event), so the batch never depends on the provider.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pgvector.django import CosineDistance

from articles.models import (
    ArticleEmbedding,
    EventWatchItem,
    NewsEvent,
    Storyline,
    StorylineEvent,
)
from core.actions import log_action
from core.errors import PipelineError
from core.vocabulary import event_topic

PENDING_WINDOW = timedelta(days=7)
ACTIVE_WINDOW = timedelta(days=14)
MEMBERS_COMPARED = 30
COSINE_ALONE = 0.85
COSINE_WITH_TAG = 0.75
SHARED_TAGS = 2
NAME_FROZEN_AFTER = 5


def _similarities(pending: list[NewsEvent], article_event: dict[int, int]) -> dict:
    """{(pending event id, other event id): cosine similarity} for close pairs only."""
    model = settings.GAPGPT_EMBEDDING_MODEL
    own = {
        row.article_id: row
        for row in ArticleEmbedding.objects.filter(
            model=model, article_id__in=[e.primary_article_id for e in pending]
        )
    }
    pairs = {}
    for event in pending:
        mine = own.get(event.primary_article_id)
        if mine is None:
            continue
        close = (
            ArticleEmbedding.objects.filter(model=model, article_id__in=list(article_event))
            .exclude(article_id=event.primary_article_id)
            .annotate(distance=CosineDistance("vector", mine.vector))
            .filter(distance__lte=1 - COSINE_WITH_TAG)
            .values_list("article_id", "distance")
        )
        for article_id, distance in close:
            pairs[event.id, article_event[article_id]] = 1 - distance
    return pairs


def link_strength(similarity: float | None, shared: int, same_topic: bool) -> float:
    """0 when not linked; otherwise a rank where closer text and more shared items win."""
    similarity = similarity or 0.0
    linked = (
        similarity >= COSINE_ALONE
        or (similarity >= COSINE_WITH_TAG and shared >= 1)
        or (shared >= SHARED_TAGS and same_topic)
    )
    return similarity + 0.1 * shared if linked else 0.0


def derived_name(events: list[NewsEvent]) -> tuple[str, str]:
    first = min(events, key=lambda e: (e.event_time, e.id))
    return first.title_fa or first.primary_article.original_title, first.title_en


def _rename(storyline: Storyline, namer) -> None:
    events = sorted(
        (link.event for link in storyline.links.select_related("event__primary_article")),
        key=lambda e: (e.event_time, e.id),
    )
    if len(events) > NAME_FROZEN_AFTER and storyline.name_fa:
        return
    name = None
    if namer is not None:
        try:
            name = namer([e.title_fa or e.primary_article.original_title for e in events[:5]])
        except PipelineError as exc:
            log_action(
                "storyline.name", "degraded", storyline=storyline.pk, error=type(exc).__name__
            )
    if not name:
        if storyline.name_fa:
            return
        name = dict(zip(("name_fa", "name_en"), derived_name(events), strict=True))
    if (name["name_fa"], name["name_en"]) == (storyline.name_fa, storyline.name_en):
        return
    if storyline.name_fa:
        storyline.previous_names.append(
            {"name_fa": storyline.name_fa, "name_en": storyline.name_en,
             "replaced_at": timezone.now().isoformat(), "events": len(events)}
        )
        log_action("storyline.rename", "renamed", storyline=storyline.pk, events=len(events))
    storyline.name_fa, storyline.name_en = name["name_fa"], name["name_en"]
    storyline.save(update_fields=["name_fa", "name_en", "previous_names", "updated_at"])


def build(now=None, namer=None) -> dict:
    """Assign recent unlinked events to storylines. `namer(titles) -> {name_fa, name_en}`."""
    now = now or timezone.now()
    eligible = (
        NewsEvent.objects.exclude(category__in=["", "other"])
        .exclude(status=NewsEvent.Status.WITHDRAWN)
        .select_related("primary_article")
    )
    pending = list(
        eligible.filter(event_time__gte=now - PENDING_WINDOW, storyline_link__isnull=True)
        .order_by("event_time", "id")
    )
    if not pending:
        return {"pending": 0, "linked": 0, "storylines_touched": 0}
    membership: dict[int, int] = {}
    for storyline_id in Storyline.objects.filter(
        last_event_at__gte=now - ACTIVE_WINDOW
    ).values_list("id", flat=True):
        for event_id in (
            StorylineEvent.objects.filter(storyline_id=storyline_id)
            .order_by("-event__event_time")
            .values_list("event_id", flat=True)[:MEMBERS_COMPARED]
        ):
            membership[event_id] = storyline_id
    members = {e.id: e for e in eligible.filter(pk__in=list(membership))}
    events = {**members, **{e.id: e for e in pending}}
    tags = defaultdict(set)
    for event_id, item_id in EventWatchItem.objects.filter(
        event_id__in=list(events)
    ).values_list("event_id", "item_id"):
        tags[event_id].add(item_id)
    similarity = _similarities(pending, {e.primary_article_id: e.id for e in events.values()})

    seen = list(members)
    touched: set[int] = set()
    with transaction.atomic():
        for event in pending:
            best, best_strength = None, 0.0
            for other_id in seen:
                other = events[other_id]
                if abs(event.event_time - other.event_time) > ACTIVE_WINDOW:
                    continue
                strength = link_strength(
                    similarity.get((event.id, other_id)),
                    len(tags[event.id] & tags[other_id]),
                    event_topic(event.category) == event_topic(other.category),
                )
                if strength > best_strength:
                    best, best_strength = other, strength
            seen.append(event.id)
            if best is None:
                continue
            storyline_id = membership.get(best.id)
            if storyline_id is None:
                storyline = Storyline.objects.create(last_event_at=best.event_time)
                StorylineEvent.objects.create(storyline=storyline, event=best)
                storyline_id = membership[best.id] = storyline.id
            StorylineEvent.objects.create(storyline_id=storyline_id, event=event)
            membership[event.id] = storyline_id
            touched.add(storyline_id)
        for storyline in Storyline.objects.filter(pk__in=touched):
            latest = max(
                e.event_time for e in events.values() if membership.get(e.id) == storyline.id
            )
            if latest > storyline.last_event_at:
                storyline.last_event_at = latest
                storyline.save(update_fields=["last_event_at", "updated_at"])
    # Naming is outside the transaction: a slow provider must not hold row locks.
    for storyline in Storyline.objects.filter(pk__in=touched):
        _rename(storyline, namer)
    linked = sum(1 for e in pending if e.id in membership)
    return {"pending": len(pending), "linked": linked, "storylines_touched": len(touched)}
