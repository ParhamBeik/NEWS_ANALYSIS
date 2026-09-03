"""Storage-level guarantees.

The two-axis rule is enforced in THREE places on purpose - the pydantic schema (rejects a
bad model answer), the model (documents intent), and a database CheckConstraint (survives
a bulk import, a management command, or a psql session that bypasses both). The legacy bug
reached production through a path that skipped validation, so the last line of defence is
the one that matters most.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from core.vocabulary import LEVELS
from inference.models import (
    Classification,
    Evaluation,
    PromptVariant,
    Run,
    new_run_id,
)
from inference.prompts import prompt_version

VERY_LOW, LOW, MEDIUM, HIGH, VERY_HIGH = LEVELS

pytestmark = pytest.mark.django_db


def _evaluation(article, variant, **scores):
    return Evaluation.objects.create(
        article=article,
        variant=variant,
        prompt_version=variant.prompt_version,
        provider=variant.provider,
        model=variant.model,
        **scores,
    )


class TestEvaluationConstraint:
    def test_two_assessed_axes_is_accepted(self, article, variant):
        row = _evaluation(
            article, variant, confidence_occurrence=HIGH, security_relevance=HIGH
        )
        assert row.pk is not None
        assert row.gold_price_impact is None

    def test_database_rejects_a_single_assessed_axis(self, article, variant):
        """An evaluation that assessed one axis cannot decide anything. Storing it as
        though it could is the failure this constraint exists to prevent."""
        with pytest.raises(IntegrityError), transaction.atomic():
            _evaluation(article, variant, confidence_occurrence=HIGH)

    def test_database_rejects_an_empty_evaluation(self, article, variant):
        with pytest.raises(IntegrityError), transaction.atomic():
            _evaluation(article, variant)

    def test_unassessed_axis_is_stored_as_null_not_a_level(self, article, variant):
        row = _evaluation(
            article, variant, confidence_occurrence=HIGH, security_relevance=HIGH
        )
        row.refresh_from_db()
        assert row.gold_price_impact is None, "an unassessed axis must never acquire a level"
        assert row.decision.notify is True


class TestAppendOnly:
    def test_rerunning_appends_rather_than_overwrites(self, article, variant):
        """The property that makes A/B comparison possible at all."""
        first = _evaluation(
            article, variant, confidence_occurrence=HIGH, gold_price_impact=HIGH
        )
        second = _evaluation(
            article, variant, confidence_occurrence=LOW, gold_price_impact=LOW
        )
        assert Evaluation.objects.filter(article=article).count() == 2
        assert first.pk != second.pk

    def test_latest_per_article_returns_the_newest_answer(self, article, variant):
        _evaluation(article, variant, confidence_occurrence=HIGH, gold_price_impact=HIGH)
        newest = _evaluation(
            article, variant, confidence_occurrence=LOW, gold_price_impact=LOW
        )
        latest = list(Evaluation.objects.latest_per_article())
        assert [row.pk for row in latest] == [newest.pk]

    def test_latest_per_article_spans_articles(self, make_article, variant):
        for _ in range(3):
            _evaluation(
                make_article(), variant, confidence_occurrence=HIGH, gold_price_impact=HIGH
            )
        assert Evaluation.objects.latest_per_article().count() == 3

    def test_for_variant_matches_on_full_identity(self, article, variant):
        _evaluation(article, variant, confidence_occurrence=HIGH, gold_price_impact=HIGH)
        other = PromptVariant.objects.create(name="challenger", model="gemini-3.5-flash")
        assert Evaluation.objects.for_variant(variant).count() == 1
        assert Evaluation.objects.for_variant(other).count() == 0


class TestPromptVariant:
    def test_prompt_version_is_stamped_from_disk_not_supplied(self, db):
        """FROZEN INVARIANT 3/4. A caller cannot set a stale version by hand - the field is
        not editable and is recomputed from the policy files on every save."""
        variant = PromptVariant.objects.create(
            name="hand-set", model="m", prompt_version="pDEADBEEF"
        )
        assert variant.prompt_version == prompt_version()

    def test_identity_is_what_the_already_answered_gate_matches(self, variant):
        assert variant.identity == ("gapgpt", "gemini-2.5-flash-lite", prompt_version())


class TestRunId:
    def test_two_runs_in_the_same_second_do_not_collide(self):
        """Second resolution is not unique; a collision took the whole run down with an
        integrity error, which is why the id carries a random suffix."""
        ids = {new_run_id() for _ in range(200)}
        assert len(ids) == 200

    def test_run_ids_sort_chronologically(self):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        earlier, later = new_run_id(now), new_run_id(now + timedelta(seconds=5))
        assert earlier < later

    def test_run_is_created_with_a_generated_id(self, db):
        run = Run.objects.create()
        assert run.run_id and Run.objects.filter(run_id=run.run_id).exists()


class TestClassification:
    def test_category_choices_are_the_frozen_vocabulary(self, article, variant):
        row = Classification.objects.create(
            article=article,
            variant=variant,
            prompt_version=variant.prompt_version,
            provider=variant.provider,
            model=variant.model,
            category="security/economics",
            confidence=HIGH,
        )
        row.full_clean()  # raises if the value is outside core.vocabulary.Category
        assert row.category == "security/economics"
