"""Events without a brief get one cheap translated headline, cached per article."""

from unittest.mock import Mock, patch

import pytest

from articles.models import NewsEvent, TitleTranslation
from core.errors import BudgetExceeded
from core.events import attach_article
from inference.tasks import translate_event_title

pytestmark = pytest.mark.django_db


def _gapgpt(raw):
    return patch("inference.jev._gapgpt", return_value=(raw, Mock(model="cheap-model")))


def test_persian_headline_gets_an_english_title_once(make_article):
    event = attach_article(make_article(original_title="افزایش قیمت بنزین در تهران"))
    NewsEvent.objects.filter(pk=event.pk).update(category="energy_commodities")
    with _gapgpt({"title": "Petrol price rises in Tehran"}) as call:
        assert translate_event_title.run(event.id)["language"] == "en"
        translate_event_title.run(event.id)
    assert call.call_count == 1  # the second run reads the per-article cache
    assert call.call_args.args[4] == "title"
    event.refresh_from_db()
    assert (event.title_en, event.title_fa) == ("Petrol price rises in Tehran", "")
    assert TitleTranslation.objects.get().source_title == "افزایش قیمت بنزین در تهران"


def test_other_events_and_budget_pressure_cost_nothing(make_article):
    event = attach_article(make_article())
    NewsEvent.objects.filter(pk=event.pk).update(category="other")
    with _gapgpt({"title": "x"}) as call:
        assert translate_event_title.run(event.id)["status"] == "skipped"
    call.assert_not_called()
    NewsEvent.objects.filter(pk=event.pk).update(category="disasters")
    with patch("inference.jev.budget.check_optional", side_effect=BudgetExceeded("80%")), \
            _gapgpt({"title": "x"}) as call:
        assert translate_event_title.run(event.id)["reason"] == "budget_or_credits"
    call.assert_not_called()
    assert not TitleTranslation.objects.exists()


def test_an_unbriefed_assessment_queues_a_translation(make_article, django_capture_on_commit_callbacks):
    from django.test import override_settings

    from inference.tasks import assess_event

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
            patch("inference.tasks.translate_event_title.delay") as translate, \
            django_capture_on_commit_callbacks(execute=True):
        assess_event.run(event.id)
    translate.assert_called_once_with(event.id)
