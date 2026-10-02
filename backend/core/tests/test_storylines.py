"""Storylines link by shared watch items or close embeddings; naming never blocks them."""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from articles.models import ArticleEmbedding, EventWatchItem, NewsEvent, Storyline, WatchItem
from core import storylines
from core.errors import Transient
from core.events import attach_article

pytestmark = pytest.mark.django_db


def assessed(make_article, title, category="sanctions_diplomacy", tags=()):
    event = attach_article(make_article(original_title=title))
    NewsEvent.objects.filter(pk=event.pk).update(category=category, iran_score=50)
    for slug in tags:
        item, _ = WatchItem.objects.get_or_create(
            slug=slug, defaults={"kind": "theme", "name_fa": slug, "name_en": slug}
        )
        EventWatchItem.objects.create(event=event, item=item)
    return event


def test_shared_items_link_events_and_a_failed_namer_keeps_a_derived_name(make_article):
    first = assessed(make_article, "Talks resume in Muscat", tags=("nuclear_talks", "oman"))
    second = assessed(make_article, "Second round ends", tags=("nuclear_talks", "oman", "iaea"))
    loner = assessed(make_article, "Wheat harvest begins", "macro_monetary", tags=("wheat",))

    def broken(titles):
        raise Transient("provider down")

    result = storylines.build(namer=broken)
    assert result == {"pending": 3, "linked": 2, "storylines_touched": 1}
    storyline = Storyline.objects.get()
    assert set(storyline.links.values_list("event", flat=True)) == {first.pk, second.pk}
    assert storyline.name_fa == "Talks resume in Muscat"
    assert not NewsEvent.objects.filter(pk=loner.pk, storyline_link__isnull=False).exists()

    # More events: renamed while young, frozen after NAME_FROZEN_AFTER, renames kept.
    def namer(titles):
        return {"name_fa": f"مذاکرات {len(titles)}", "name_en": f"Talks {len(titles)}"}

    assessed(make_article, "Third round", tags=("nuclear_talks", "oman"))
    storylines.build(namer=namer)
    storyline.refresh_from_db()
    assert storyline.name_en == "Talks 3"
    assert storyline.previous_names[0]["name_fa"] == "Talks resume in Muscat"
    for n in range(4):
        assessed(make_article, f"Round {n + 4}", tags=("nuclear_talks", "oman"))
    storylines.build(namer=namer)
    storyline.refresh_from_db()
    assert storyline.links.count() == 7 and storyline.name_en == "Talks 3"
    page = APIClient().get(f"/api/public/events/{first.pk}/").data["storyline"]
    assert page["name_en"] == "Talks 3" and len(page["events"]) == 7


def test_close_embeddings_link_events_without_shared_items(make_article):
    first = assessed(make_article, "Tanker seized near Hormuz")
    second = assessed(make_article, "Navy confirms tanker seizure", "conflict_security")
    vector = [1.0] + [0.0] * 1535
    nearby = [0.99, 0.1] + [0.0] * 1534
    for event, values in ((first, vector), (second, nearby)):
        ArticleEmbedding.objects.create(
            article=event.primary_article, model=settings.GAPGPT_EMBEDDING_MODEL,
            dimensions=1536, vector=values,
        )
    storylines.build()
    assert Storyline.objects.get().links.count() == 2
