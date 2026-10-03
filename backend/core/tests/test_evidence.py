"""Evidence level counts independent source groups, before and after sources carry them."""

from types import SimpleNamespace

import pytest

from articles.models import NewsEvent
from core.events import attach_article, evidence_level, refresh_event
from sources.models import Source, Strategy

pytestmark = pytest.mark.django_db


def report(name, group=None):
    source = SimpleNamespace(name=name)
    if group is not None:
        source.independence_group = group
    return SimpleNamespace(source=source)


def test_groups_collapse_copies_and_official_wins_but_disputed_sticks():
    assert evidence_level([report("irna", "state"), report("mehr", "state")]) == "single"
    assert evidence_level([report("irna", ""), report("mehr", "")]) == "multi"
    assert evidence_level([report("irna", "state"), report("cbi", "official")]) == "official"
    assert evidence_level([report("irna"), report("bbc")], "disputed") == "disputed"


def test_second_source_makes_an_event_multi(make_article):
    event = attach_article(make_article())
    assert event.evidence_level == NewsEvent.Evidence.SINGLE
    other = Source.objects.create(
        name="isna", strategy=Strategy.RSS_SABA, url="https://www.isna.ir/rss"
    )
    event.articles.add(make_article(source=other))
    refresh_event(event)
    event.refresh_from_db()
    assert event.evidence_level == NewsEvent.Evidence.MULTI


def test_a_contradiction_from_another_independent_group_disputes_the_event():
    lead, state_copy, bbc = report("irna", "state"), report("irib", "state"), report("bbc")
    aggregator = report("khabarfoori")
    aggregator.source.role = "aggregator"
    articles = [lead, state_copy, bbc, aggregator]
    assert evidence_level(articles, "", [bbc], lead) == "disputed"
    # The lead's own group revising itself, or an aggregator relaying, is not a dispute.
    assert evidence_level(articles, "", [state_copy], lead) == "multi"
    assert evidence_level(articles, "", [aggregator], lead) == "multi"


def test_a_recrawled_undated_report_keeps_its_event_at_first_sight(make_article):
    from datetime import timedelta

    from django.utils import timezone

    from articles.models import Article

    undated = make_article(published_at=None)
    first_seen = timezone.now() - timedelta(hours=20)
    # Ingest refreshes fetched_at on every re-crawl; created_at is when we first saw it.
    Article.objects.filter(pk=undated.pk).update(created_at=first_seen, fetched_at=timezone.now())
    undated.refresh_from_db()
    event = attach_article(undated)
    refresh_event(event)
    event.refresh_from_db()
    assert event.event_time == first_seen
