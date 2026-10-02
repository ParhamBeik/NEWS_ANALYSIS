"""Watch-item vocabulary: the alias shortlist decides what Jev is even asked about."""

from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import override_settings

from articles.models import WatchItem
from core.events import attach_article
from core.watch import shortlist
from inference import jev
from inference.tasks import assess_event

pytestmark = pytest.mark.django_db


def test_fixture_loads_and_disables_items_it_no_longer_lists():
    WatchItem.objects.create(slug="retired", kind="theme", name_fa="x", name_en="x")
    call_command("seed_watch_items")
    assert WatchItem.objects.filter(enabled=True).count() >= 150
    assert set(WatchItem.objects.values_list("kind", flat=True)) == {"asset", "actor", "theme"}
    assert not WatchItem.objects.get(slug="retired").enabled


def test_shortlist_folds_persian_and_respects_word_starts():
    call_command("seed_watch_items")
    items = WatchItem.objects.filter(enabled=True)
    # Arabic YEH, an ezafe suffix and a ZWNJ plural all still match.
    found = shortlist("قيمت طلای ۱۸ عیار و دلار‌ها بالا رفت؛ بانک مرکزی واکنش نشان داد", items)
    assert {"gold_18k", "usd_irr", "cbi"} <= set(found)
    # طلاق (divorce) starts with طلا but is not gold; "Fed" must not match "federal".
    assert shortlist("آمار طلاق در federal court", items) == {}


def test_assessment_tags_event_from_typesafe_watch_scores(make_article):
    call_command("seed_watch_items")
    event = attach_article(make_article(
        original_title="Brent jumps as tanker traffic through the Strait of Hormuz slows",
    ))
    response = {"model": "jev", "answers": {
        "category": {"choice": "energy_commodities", "confidence": 0.9},
        "iran": {"score": 2, "confidence": 0.9},
        "global": {"score": 2, "confidence": 0.9},
        **{f"asset_{key}": {"score": 1} for key in
           ("fx", "gold", "tehran_index", "oil", "bitcoin")},
        "watch_brent": {"score": 2.0},
        "watch_strait_of_hormuz": {"score": 1.4},
        "watch_gulf_shipping": {"score": 0.3},
    }}
    with override_settings(TYPESAFE_API_KEY="test-key"), \
            patch("inference.jev.decide", return_value=response) as decide, \
            patch("inference.tasks.summarize_event.delay"):
        assert assess_event.run(event.id)["status"] == "assessed"
    asked = decide.call_args.args[3]
    assert {"brent", "strait_of_hormuz", "gulf_shipping"} <= set(asked)
    assert set(event.watch_links.values_list("item__slug", flat=True)) == {
        "brent", "strait_of_hormuz",
    }


def test_fallback_asks_one_multi_label_question_and_drops_unknown_keys():
    watch = {"brent": "Brent crude (نفت برنت)", "opec": "OPEC+ (اوپک)"}
    questions = jev._questions(None, watch, multi=True)
    assert "watch_items" in questions and "watch_brent" not in questions
    raw = {name: {"score": 1, "choice": "energy_commodities", "confidence": 1}
           for name in questions}
    raw["watch_items"] = {"choices": ["opec", "invented"], "confidence": 0.7}
    answers = jev._fallback_answers(raw, questions)
    assert jev.watch_tags(answers) == ["opec"]
    assert len(jev._questions(None, watch)) == len(jev._questions(None)) + 2
