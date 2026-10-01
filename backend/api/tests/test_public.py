"""Reader boundary: public events, no article body, and honest price windows."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from articles.models import AlertSubscription, Article, EventAlert, NewsEvent
from articles.tasks import send_event_alert
from core.events import attach_article
from market.models import PriceSnapshot, Symbol

pytestmark = pytest.mark.django_db


def make_event(source, *, title="Iran currency policy changes after central bank decision"):
    now = timezone.now()
    article = Article.objects.create(
        url=f"https://example.com/{Article.objects.count() + 1}", source=source,
        original_title=title, lead="This is a published summary with useful evidence.",
        content="Full captured source text must stay private.", content_hash="a" * 32,
        published_at=now - timedelta(hours=2), fetched_at=now - timedelta(hours=1),
    )
    return attach_article(article)


def test_public_event_is_developing_and_does_not_expose_captured_body(source):
    event = make_event(source)
    api = APIClient()
    listing = api.get("/api/public/events/")
    assert listing.status_code == 200
    assert listing.data["results"][0]["id"] == event.id
    detail = api.get(f"/api/public/events/{event.id}/")
    assert detail.status_code == 200
    assert detail.data["status"] == NewsEvent.Status.DEVELOPING
    assert "Full captured source text" not in str(detail.data)
    assert api.get("/api/articles/").status_code in {401, 403}


def test_public_feed_excludes_prefiltered_articles(source):
    event = make_event(source)
    Article.objects.filter(pk=event.primary_article_id).update(prefilter_reason="native_category:sports")
    assert APIClient().get("/api/public/events/").data["results"] == []


def test_timeline_omits_change_when_no_valid_pre_event_price(source):
    event = make_event(source)
    NewsEvent.objects.filter(pk=event.pk).update(category="macro", iran_score=90)
    PriceSnapshot.objects.create(
        symbol=Symbol.GOLD_18K, price=100, observed_at=timezone.now() - timedelta(hours=1),
    )
    response = APIClient().get("/api/public/assets/gold_18k/timeline/?range=1W&events=all")
    assert response.status_code == 200
    assert response.data["events"][0]["observed_changes"] == {}


@override_settings(NEWS_ALERTS_ENABLED=True, NEWS_VAPID_PUBLIC_KEY="public",
                   NEWS_VAPID_PRIVATE_KEY="private", NEWS_VAPID_SUBJECT="mailto:news@example.com")
def test_alert_subscription_is_authenticated_and_rejects_internal_endpoints():
    api = APIClient()
    path = "/api/alerts/subscriptions/"
    payload = {"subscription": {
        "endpoint": "https://fcm.googleapis.com/fcm/send/example",
        "keys": {"p256dh": "a" * 50, "auth": "b" * 30},
    }}
    assert api.post(path, payload, format="json").status_code in {401, 403}
    user = get_user_model().objects.create_user(username="reader", password="not-a-real-secret")
    api.force_authenticate(user=user)
    payload["subscription"]["endpoint"] = "https://127.0.0.1/internal"
    assert api.post(path, payload, format="json").status_code == 400
    payload["subscription"]["endpoint"] = "https://fcm.googleapis.com/fcm/send/example"
    assert api.post(path, payload, format="json").status_code == 200
    assert AlertSubscription.objects.filter(user=user).count() == 1


@override_settings(NEWS_ALERTS_ENABLED=True, NEWS_VAPID_PRIVATE_KEY="private",
                   NEWS_VAPID_SUBJECT="mailto:news@example.com")
def test_event_alert_is_sent_once_and_contains_only_reader_url(source):
    event = make_event(source)
    user = get_user_model().objects.create_user(username="reader2")
    subscription = AlertSubscription.objects.create(
        user=user, endpoint="https://fcm.googleapis.com/fcm/send/example",
        p256dh="a" * 50, auth="b" * 30,
    )
    with patch("pywebpush.webpush") as push:
        assert send_event_alert.run(event.id, subscription.id)["status"] == "sent"
        assert send_event_alert.run(event.id, subscription.id)["status"] == "already_sent"
    assert push.call_count == 1
    assert f"/events/{event.id}" in push.call_args.kwargs["data"]
    assert EventAlert.objects.get(event=event, subscription=subscription).sent_at
