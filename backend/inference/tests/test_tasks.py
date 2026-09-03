"""Orchestration: who gets asked, who gets skipped, and who closes the books.

None of this touches a provider. What is under test is the DISPATCH decision - which is
where the money is spent and where an A/B experiment quietly stops being one.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from inference.models import (
    Classification,
    MemoryStrategy,
    NodeEvent,
    NodeStatus,
    PromptVariant,
    Run,
    RunStatus,
    Summary,
)
from inference.tasks import _already_answered, finalize_stale_runs, run_cycle

pytestmark = pytest.mark.django_db


def _answer(model_class, article, variant, **extra):
    return model_class.objects.create(
        article=article,
        variant=variant,
        prompt_version=variant.prompt_version,
        provider=variant.provider,
        model=variant.model,
        **extra,
    )


def _classify(article, variant, category="security"):
    return _answer(Classification, article, variant, category=category)


@pytest.fixture
def challenger(variant) -> PromptVariant:
    """The second arm of the default experiment.

    Same provider, same model, same prompt as `control` - `seed_variants` gives both arms
    `settings.GAPGPT_MODEL` - and differs ONLY in memory strategy. That is precisely the
    configuration in which an identity-only gate cannot tell the two apart.
    """
    return PromptVariant.objects.create(
        name="semantic-memory",
        model=variant.model,
        memory_strategy=MemoryStrategy.SEMANTIC,
        memory_k=3,
        is_active=True,
    )


class TestAlreadyAnswered:
    def test_a_second_arm_is_still_asked_when_it_shares_a_model(
        self, article, variant, challenger
    ):
        """THE test for the A/B experiment existing at all.

        Keyed on (provider, model, prompt) alone, the control arm's answer satisfied the
        gate for the memory arm too, every node for the second variant returned SKIPPED,
        and the lab could never collect two answers for one article - which is the only
        thing it is for.
        """
        _classify(article, variant)
        assert _already_answered("classify", article.pk, variant) is True
        assert _already_answered("classify", article.pk, challenger) is False

    def test_the_same_variant_is_not_asked_twice(self, article, variant):
        _classify(article, variant)
        assert _already_answered("classify", article.pk, variant) is True

    def test_repointing_a_variant_at_a_new_model_re_runs_it(self, article, variant):
        """The property the identity columns were there for in the first place."""
        _classify(article, variant)
        variant.model = "gemini-3.5-flash"
        variant.save()
        assert _already_answered("classify", article.pk, variant) is False


class TestRunCycle:
    @pytest.fixture
    def dispatched(self, monkeypatch) -> list[tuple]:
        calls: list[tuple] = []
        monkeypatch.setattr(
            "inference.tasks.process_article.delay",
            lambda *args: calls.append(args),
        )
        return calls

    def test_every_active_variant_is_dispatched(
        self, make_article, variant, challenger, dispatched
    ):
        article = make_article()
        run_cycle()
        assert {call[1] for call in dispatched} == {variant.pk, challenger.pk}
        assert {call[0] for call in dispatched} == {article.pk}

    def test_a_settled_article_is_not_re_dispatched(
        self, make_article, variant, dispatched
    ):
        """Re-offering an answered article every 30 minutes wrote one SKIPPED NodeEvent per
        node per cycle - tens of thousands of non-events a day - and every one of them
        landed in the node_outcomes counts on /ops."""
        article = make_article()
        _classify(article, variant)
        _answer(Summary, article, variant, optimized_title="t", one_line="l")

        assert run_cycle()["dispatched"] == 0
        assert dispatched == []

    def test_an_other_verdict_settles_without_a_summary(
        self, make_article, variant, dispatched
    ):
        """`other` stops the chain by design, so waiting for a summary that will never be
        written would re-dispatch it forever."""
        article = make_article()
        _classify(article, variant, category="other")
        assert run_cycle()["dispatched"] == 0

    def test_a_chain_that_died_mid_way_is_picked_up_again(
        self, make_article, variant, dispatched
    ):
        """Classified but never summarised is a worker killed between two nodes. Healing
        that on the next cycle is the reason the gate is not simply 'has a classification'.
        """
        article = make_article()
        _classify(article, variant)
        assert run_cycle()["dispatched"] == 1

    def test_a_cycle_with_nothing_to_do_does_not_create_a_run(
        self, make_article, variant, dispatched
    ):
        article = make_article()
        _classify(article, variant)
        _answer(Summary, article, variant, optimized_title="t", one_line="l")
        run_cycle()
        assert Run.objects.count() == 0

    def test_articles_outside_the_rolling_window_are_left_alone(
        self, make_article, variant, dispatched, settings
    ):
        """An unbounded queryset re-offers an article nothing will ever answer for the life
        of the deployment."""
        settings.NEWS_ROLLING_WINDOW_DAYS = 2
        make_article(fetched_at=timezone.now() - timedelta(days=30))
        assert run_cycle()["dispatched"] == 0


class TestFinalizeStaleRuns:
    def _event(self, run, *, age_minutes: int, cost="0.002000"):
        event = NodeEvent.objects.create(
            run=run, node="classify", status=NodeStatus.SUCCESS,
            tokens_in=100, tokens_out=50, cost_usd=cost,
        )
        NodeEvent.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - timedelta(minutes=age_minutes)
        )
        return event

    def test_a_drained_run_is_closed_and_its_cost_rolled_up(self, article):
        """Without this every run stayed `running` with cost_usd=0 forever, so the one
        table an operator reads for spend reported $0.0000 for runs that spent money."""
        run = Run.objects.create(started_at=timezone.now() - timedelta(hours=1))
        self._event(run, age_minutes=30)
        self._event(run, age_minutes=25)

        assert finalize_stale_runs()["closed"] == 1
        run.refresh_from_db()
        assert run.status == RunStatus.SUCCESS
        assert float(run.cost_usd) == pytest.approx(0.004)
        assert run.tokens_in == 200
        assert run.finished_at is not None

    def test_a_run_still_writing_events_is_left_alone(self):
        run = Run.objects.create(started_at=timezone.now() - timedelta(hours=1))
        self._event(run, age_minutes=0)
        assert finalize_stale_runs()["closed"] == 0
        run.refresh_from_db()
        assert run.status == RunStatus.RUNNING

    def test_an_aborted_run_keeps_the_status_that_explains_it(self):
        """A budget abort is the answer to "why did this stop?". Overwriting it with
        `success` because the tasks drained would erase the only record of the ceiling."""
        run = Run.objects.create(
            started_at=timezone.now() - timedelta(hours=1),
            status=RunStatus.ABORTED,
            error="daily ceiling reached",
        )
        self._event(run, age_minutes=30)
        assert finalize_stale_runs()["closed"] == 0
        run.refresh_from_db()
        assert run.status == RunStatus.ABORTED
