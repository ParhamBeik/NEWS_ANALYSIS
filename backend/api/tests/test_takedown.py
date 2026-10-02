"""Takedown hides from every public surface with an audit trail; link-out sources stay unquoted."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tasks import fan_out_event
from articles.models import Article, NewsEvent, TakedownLog
from core.events import attach_article
from sources.models import LicenseMode, Source, Strategy

from .test_public import make_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff():
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_user(
        "editor", password="x", is_staff=True))
    return client


def test_staff_hide_removes_an_event_everywhere_and_is_audited(source, staff, settings):
    event = make_event(source)
    url = f"/api/staff/events/{event.id}/visibility/"
    reader = APIClient()
    assert staff.post(url, {"action": "hide"}).status_code == 400  # a reason is required
    reader.force_authenticate(get_user_model().objects.create_user("reader", password="x"))
    assert reader.post(url, {"action": "hide", "reason": "x"}).status_code == 403

    assert staff.post(url, {"action": "hide", "reason": "court order 12"}).data["changed"]
    public = APIClient()
    assert public.get("/api/public/events/").data["results"] == []
    assert public.get(f"/api/public/events/{event.id}/").status_code == 404
    assert not Article.objects.canonical().filter(pk=event.primary_article_id).exists()
    settings.NEWS_ALERTS_ENABLED = True
    assert fan_out_event.run(event.id)["status"] == "not_alertable"

    staff.post(url, {"action": "unhide", "reason": "order lifted"})
    assert public.get(f"/api/public/events/{event.id}/").status_code == 200
    log = staff.get(url).data["log"]
    assert [(row["action"], row["reason"], row["by"]) for row in log] == [
        ("unhide", "order lifted", "editor"), ("hide", "court order 12", "editor")]
    row = TakedownLog.objects.first()
    with pytest.raises(ValueError):
        row.save()
    with pytest.raises(ValueError):
        row.delete()


def test_hiding_one_report_drops_it_from_the_event_sources(source, staff):
    event = make_event(source)
    copy = Article.objects.create(
        url="https://example.com/copy", source=source, original_title="Second report",
        content_hash="b" * 32, fetched_at=event.primary_article.fetched_at,
    )
    event.articles.add(copy)
    staff.post(f"/api/staff/articles/{copy.id}/visibility/",
               {"action": "hide", "reason": "copyright notice"})
    sources = APIClient().get(f"/api/public/events/{event.id}/").data["sources"]
    assert [row["url"] for row in sources] == [event.primary_article.url]
    # Hiding the lead report hides the event it heads.
    staff.post(f"/api/staff/articles/{event.primary_article_id}/visibility/",
               {"action": "hide", "reason": "copyright notice"})
    assert not NewsEvent.objects.visible().filter(pk=event.id).exists()


def test_facts_link_out_sources_never_expose_text_publicly():
    paywalled = Source.objects.create(
        name="ft", display_name="Financial Times", strategy=Strategy.RSS_GENERIC,
        url="https://www.ft.com/rss", language="en", license_mode=LicenseMode.FACTS_LINK_OUT,
    )
    article = Article.objects.create(
        url="https://www.ft.com/content/oil", source=paywalled,
        original_title="Oil tanker seized in the Gulf",
        lead="Paywalled standfirst that must not be republished.",
        content="Paywalled body that must not be republished.", content_hash="c" * 32,
        fetched_at=timezone.now(),
    )
    event = attach_article(article)
    public = APIClient()
    detail = public.get(f"/api/public/events/{event.id}/").data
    listing = public.get("/api/public/events/").data
    for payload in (detail, listing):
        assert "Paywalled" not in str(payload)
    source_row = detail["sources"][0]
    assert (source_row["name"], source_row["url"], source_row["headline"]) == (
        "Financial Times", "https://www.ft.com/content/oil", "Oil tanker seized in the Gulf")
