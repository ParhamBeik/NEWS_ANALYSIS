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
