import pytest
from rest_framework.test import APIClient

from articles.models import EventReview, NewsEvent
from core.events import attach_article

pytestmark = pytest.mark.django_db


@pytest.fixture
def review(make_article):
    event = attach_article(make_article())
    event.articles.add(make_article())
    NewsEvent.objects.filter(pk=event.pk).update(
        category="markets", iran_score=50, global_score=75, assessment_confidence=0.5
    )
    return EventReview.objects.create(event=event, reason="high_impact_uncertain")


def client_for(user, *, staff):
    user.is_staff = staff
    user.save(update_fields=["is_staff"])
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def test_event_review_endpoints_are_staff_only(user, review):
    api = client_for(user, staff=False)
    base = f"/api/review/events/{review.event_id}/"
    assert api.get("/api/review/queue/").status_code == 403
    assert api.get("/api/review/stats/").status_code == 403
    assert api.post(base, {"action": "agree"}, format="json").status_code == 403
    assert api.post(f"{base}split/", {"article_id": 1}, format="json").status_code == 403
    assert APIClient().get("/api/review/queue/").status_code in (401, 403)


def test_queue_agree_split_and_session_stats(user, review, django_assert_max_num_queries):
    api = client_for(user, staff=True)
    with django_assert_max_num_queries(8):
        queue = api.get("/api/review/queue/?limit=25").json()
    card = queue["results"][0]
    assert queue["pending"] == 1
    assert (card["id"], card["iran_tier"], card["global_tier"], card["category"]) == (
        review.event_id, 2, 3, "markets",
    )
    assert len(card["articles"]) == 2

    base = f"/api/review/events/{review.event_id}/"
    assert api.post(base, {"action": "fix", "category": "x"}, format="json").status_code == 400
    saved = api.post(base, {"action": "agree"}, format="json").json()
    assert (saved["status"], saved["reviewed_iran_score"]) == ("reviewed", 50)

    stray = card["articles"][1]["id"]
    split = api.post(f"{base}split/", {"article_id": stray}, format="json")
    assert split.status_code == 201
    assert len(split.json()["card"]["articles"]) == 1
    assert api.post(f"{base}split/", {"article_id": stray}, format="json").status_code == 400

    stats = api.get("/api/review/stats/", {"since": "2000-01-01T00:00:00Z"}).json()
    assert (stats["reviewed"], stats["agreement_rate"]) == (1, 1.0)
