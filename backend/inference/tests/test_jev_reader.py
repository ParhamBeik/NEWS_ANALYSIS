"""The reader path must degrade safely when classification is uncertain or unavailable."""

from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from articles.models import ArticleRevision, EventReview, NewsEvent
from core.errors import BudgetExceeded, Permanent
from core.events import attach_article
from inference import jev
from inference.tasks import assess_event

pytestmark = pytest.mark.django_db


def test_typesafe_402_is_credit_exhaustion():
    with override_settings(TYPESAFE_API_KEY="test-key"), \
            patch("inference.jev.requests.post") as post:
        post.return_value = Mock(status_code=402)
        with pytest.raises(BudgetExceeded):
            jev.decide({"title": "x"}, "run-test")


def test_without_typesafe_key_decisions_use_the_gapgpt_fallback():
    raw = {
        "category": {"choice": "energy_commodities", "confidence": 0.8},
        "iran": {"score": 3, "confidence": 0.7},
        "global": {"score": 2, "confidence": 0.9},
        **{f"asset_{k}": {"score": 1, "confidence": 0.5}
           for k in ("fx", "gold", "tehran_index", "oil", "bitcoin")},
    }
    usage = Mock(model="gemini-3.1-flash-lite")
    with override_settings(TYPESAFE_API_KEY="", GAPGPT_API_KEY="k"), \
            patch("inference.jev._gapgpt", return_value=(raw, usage)) as call:
        answers = jev.decide({"title": "x"}, "run-test")["answers"]
    assert call.called
    assert answers["category"]["choice"] == "energy_commodities"
    assert answers["iran"]["score"] == 3.0


def test_fallback_rejects_answers_jev_could_never_give():
    questions = jev._questions(None)
    bad = {name: {"score": 9, "choice": "energy_commodities", "confidence": 1} for name in questions}
    with pytest.raises(Permanent):
        jev._fallback_answers(bad, questions)


def test_uncertain_high_impact_event_enters_review_without_losing_correction(make_article):
    article = make_article(original_title="Bank announces a material currency policy change")
    event = attach_article(article)
    ArticleRevision.objects.create(
        article=article, title="Previous title", content_hash="a" * 32,
        status="live",
    )
    response = {"model": "typesafe/jev-1.13", "usage": {"cost": 0.00002}, "answers": {
        "category": {"choice": "macro_monetary", "confidence": 0.62},
        "iran": {"score": 3.7, "confidence": 0.64},
        "global": {"score": 2.0, "confidence": 0.9},
        **{f"asset_{key}": {"score": 2.0} for key in
           ("fx", "gold", "tehran_index", "oil", "bitcoin")},
    }}
    with override_settings(TYPESAFE_API_KEY="test-key"), \
            patch("inference.jev.decide", return_value=response), \
            patch("inference.tasks.summarize_event.delay"):
        assert assess_event.run(event.id)["status"] == "assessed"
    event.refresh_from_db()
    assert event.status == NewsEvent.Status.CORRECTED
    assert event.iran_score == 92
    assert EventReview.objects.get(event=event).reason == "high_impact_uncertain"


def test_provider_credit_failure_keeps_developing_event(make_article):
    event = attach_article(make_article())
    with override_settings(TYPESAFE_API_KEY="test-key"), \
            patch("inference.jev.decide", side_effect=BudgetExceeded("402")):
        assert assess_event.run(event.id)["status"] == "unassessed"
    event.refresh_from_db()
    assert event.status == NewsEvent.Status.DEVELOPING
    assert event.assessments.count() == 0


def test_high_confidence_cross_language_match_keeps_both_source_articles(make_article):
    first = attach_article(make_article(original_title="Iran central bank changes reserve policy"))
    second = attach_article(make_article(
        original_title="بانک مرکزی ایران سیاست ذخیره را تغییر داد",
        url="https://example.org/persian-reserve-policy",
    ))
    response = {"model": "typesafe/jev-1.13", "usage": {"cost": 0.00002}, "answers": {
        "same_event": {"choice": f"event_{first.id}",
                       "probabilities": {f"event_{first.id}": 0.96}},
        "category": {"choice": "macro_monetary", "confidence": 0.95},
        "iran": {"score": 3, "confidence": 0.95},
        "global": {"score": 2, "confidence": 0.95},
        **{f"asset_{key}": {"score": 1} for key in
           ("fx", "gold", "tehran_index", "oil", "bitcoin")},
    }}
    with override_settings(TYPESAFE_API_KEY="test-key"), \
            patch("inference.jev.decide", return_value=response), \
            patch("inference.tasks.summarize_event.delay"):
        result = assess_event.run(second.id)
    assert result["event"] == first.id
    assert NewsEvent.objects.count() == 1
    assert first.articles.count() == 2


def test_a_merging_assessment_tells_the_alert_fan_out_it_merged(make_article):
    first = attach_article(make_article(original_title="Iran central bank changes reserve policy"))
    second = attach_article(make_article(original_title="Reserve policy changed in Tehran"))
    response = {"model": "typesafe/jev-1.13", "usage": {"cost": 0}, "answers": {
        "same_event": {"choice": f"event_{first.id}",
                       "probabilities": {f"event_{first.id}": 0.96}},
        "category": {"choice": "macro_monetary", "confidence": 0.95},
        "iran": {"score": 3, "confidence": 0.95},
        "global": {"score": 2, "confidence": 0.95},
        **{f"asset_{key}": {"score": 1} for key in
           ("fx", "gold", "tehran_index", "oil", "bitcoin")},
    }}
    with override_settings(TYPESAFE_API_KEY="test-key", NEWS_ALERTS_ENABLED=True), \
            patch("inference.jev.decide", return_value=response), \
            patch("inference.tasks.summarize_event.delay"), \
            patch("articles.tasks.alert_event.apply_async"), \
            patch("accounts.tasks.fan_out_event.apply_async") as fan_out:
        assess_event.run(second.id)
    assert fan_out.call_args.kwargs == {
        "args": [first.id], "kwargs": {"merged": True}, "countdown": 30,
    }


def test_malformed_jev_answer_does_not_merge_events(make_article):
    first = attach_article(make_article(original_title="Iran bank updates reserves"))
    second = attach_article(make_article(
        original_title="بانک مرکزی ذخایر را به‌روز کرد",
        url="https://example.org/reserve-update",
    ))
    response = {"answers": {
        "same_event": {"choice": f"event_{first.id}",
                       "probabilities": {f"event_{first.id}": 0.99}},
        "category": {"choice": "macro_monetary", "confidence": 0.9},
        "iran": {"score": 7, "confidence": 0.9},
        "global": {"score": 2, "confidence": 0.9},
        **{f"asset_{key}": {"score": 1} for key in
           ("fx", "gold", "tehran_index", "oil", "bitcoin")},
    }}
    with override_settings(TYPESAFE_API_KEY="test-key"), \
            patch("inference.jev.decide", return_value=response):
        assert assess_event.run(second.id)["status"] == "unassessed"
    assert NewsEvent.objects.count() == 2


def test_low_impact_event_gets_no_paid_brief(make_article):
    event = attach_article(make_article(original_title="Provincial bank opens a new branch office"))
    response = {"model": "jev", "answers": {
        "category": {"choice": "markets_companies", "confidence": 0.9},
        "iran": {"score": 1, "confidence": 0.9},
        "global": {"score": 0, "confidence": 0.9},
        **{f"asset_{key}": {"score": 0} for key in
           ("fx", "gold", "tehran_index", "oil", "bitcoin")},
    }}
    with override_settings(TYPESAFE_API_KEY="test-key"), \
            patch("inference.jev.decide", return_value=response), \
            patch("inference.tasks.summarize_event.delay") as brief:
        assert assess_event.run(event.id)["status"] == "assessed"
    brief.assert_not_called()
