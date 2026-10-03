"""Shadow eval: labelled items in, one compact EvalRun out, no event writes.

Provider answers are mocked; the gate logic is what is under test.
"""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from articles.models import EventAssessment, EventReview, GroupingDecision, NewsEvent
from core import shadow_eval
from core.errors import BudgetExceeded, Permanent
from core.events import attach_article
from inference import circuit
from inference.models import CircuitState, EvalRun
from sources.models import Source, Strategy

pytestmark = pytest.mark.django_db

TYPESAFE = override_settings(TYPESAFE_API_KEY="test-key", NEWS_EVAL_MIN_LABELS=2)


def _review(make_article, *, topic="energy_commodities", iran=75, global_=25, **article):
    event = attach_article(make_article(**article))
    EventReview.objects.create(
        event=event, reason="audit_sample", status=EventReview.Status.REVIEWED,
        reviewed_category=topic, reviewed_iran_score=iran, reviewed_global_score=global_,
        reviewed_at=timezone.now(),
    )
    return event


def _answers(topic="energy_commodities", iran=3.0, global_=1.0, same=None):
    answers = {
        "category": {"choice": topic, "confidence": 0.9},
        "iran": {"score": iran, "confidence": 0.9},
        "global": {"score": global_, "confidence": 0.9},
    }
    if same:
        answers["same_event"] = {"choice": same, "probabilities": {same: 0.95}}
    return {"model": "jev-1.13.0", "answers": answers}


@pytest.fixture
def english(db):
    return Source.objects.create(
        name="reuters", strategy=Strategy.RSS_SABA, url="https://example.com/rss", language="en",
    )


def test_passing_run_stores_metrics_without_touching_events(make_article, english):
    fa = _review(make_article)
    en = _review(make_article, source=english, url="https://example.com/a")
    other = attach_article(make_article(original_title="unrelated"))
    same = make_article(original_title="joining report")
    GroupingDecision.objects.create(article=same, event=fa, decision="same")
    GroupingDecision.objects.create(article=other.primary_article, event=en, decision="not_same")

    def decide(state, run_id, candidates=None):
        assert run_id.startswith("eval-")
        if state["title"] == "joining report":
            return _answers(same=f"event_{fa.id}")
        return _answers()

    with TYPESAFE, patch("inference.jev.decide", side_effect=decide):
        call_command("shadow_eval", stdout=StringIO())

    row = EvalRun.objects.get()
    assert (row.verdict, row.backend, row.model) == ("pass", "typesafe", "jev-1.13.0")
    assert (row.labelled, row.grouping_pairs, row.failed) == (2, 2, 0)
    assert len(row.question_hash) == 64
    assert row.metrics["overall"]["topic_accuracy"] == 1.0
    assert set(row.metrics["languages"]) == {"fa", "en"}
    assert row.metrics["grouping"] == {
        "pairs": 2, "true_positive": 1, "false_positive": 0, "false_negative": 0,
        "precision": 1.0, "recall": 1.0,
    }
    assert EventAssessment.objects.count() == 0
    assert NewsEvent.objects.get(pk=fa.pk).iran_score is None


def test_wrong_topics_and_unusable_answers_fail_the_gate(make_article, english):
    _review(make_article)
    _review(make_article, topic="disasters", iran=0, global_=0)
    _review(make_article, source=english, url="https://example.com/b")
    responses = [
        _answers(),  # newest review first: the English one, correct
        _answers(topic="other", iran=0.0, global_=0.0),  # wrong topic, tiers right
        Permanent("fallback answer missing iran"),  # counts as a miss
    ]
    with TYPESAFE, patch("inference.jev.decide", side_effect=responses):
        with pytest.raises(CommandError, match="topic accuracy"):
            call_command("shadow_eval", stdout=StringIO())
    row = EvalRun.objects.get()
    assert row.verdict == "fail" and row.failed == 1
    assert row.metrics["overall"]["topic_accuracy"] == pytest.approx(0.333)
    assert row.metrics["languages"]["en"]["topic_accuracy"] == 1.0
    assert row.metrics["topics"]["disasters"]["global_tier_exact"] == 1.0


def test_too_few_labels_is_its_own_verdict(make_article):
    _review(make_article)
    with override_settings(TYPESAFE_API_KEY="k"), \
            patch("inference.jev.decide", return_value=_answers()):
        with pytest.raises(CommandError, match="insufficient_labels"):
            call_command("shadow_eval", stdout=StringIO())
    assert EvalRun.objects.get().reasons == ["1 labelled items, need 50"]


def test_empty_wallet_aborts_and_opens_the_circuit(make_article):
    _review(make_article)
    _review(make_article)
    with TYPESAFE, patch("inference.jev.decide", side_effect=BudgetExceeded("402")) as call:
        with pytest.raises(CommandError, match="aborted"):
            call_command("shadow_eval", stdout=StringIO())
    assert call.call_count == 1
    assert circuit.current().state == CircuitState.OPEN_BUDGET
    with TYPESAFE, pytest.raises(CommandError, match="circuit open"):
        call_command("shadow_eval", stdout=StringIO())
    assert EvalRun.objects.count() == 1


def test_dry_run_estimates_without_asking(make_article):
    _review(make_article)
    out = StringIO()
    with patch("inference.jev.decide") as call, override_settings(GAPGPT_API_KEY="k"):
        call_command("shadow_eval", "--dry-run", "--language", "fa", stdout=out)
    assert not call.called and not EvalRun.objects.exists()
    assert "backend=gapgpt reviews=1" in out.getvalue()
    estimate = shadow_eval.estimate(shadow_eval.labelled_reviews(), [], "gapgpt")
    assert estimate["tokens_in"] > 0 and estimate["cost_usd"] > 0


def test_eval_runs_endpoint_is_staff_only(user):
    EvalRun.objects.create(
        backend="gapgpt", model="gapgpt:m", question_hash="h", language="all",
        metrics={}, verdict="insufficient_labels",
    )
    api = APIClient()
    api.force_authenticate(user=user)
    assert api.get("/api/ops/evals/").status_code == 403
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    body = api.get("/api/ops/evals/").json()
    assert body["runs"][0]["verdict"] == "insufficient_labels"
