"""The spend and request ceilings.

These matter more than most tests in the suite because the thing they protect is real
money, and because the single-process version of this code was silently wrong the moment
it ran under more than one Celery worker.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.test import override_settings

from core.errors import BudgetExceeded
from inference import budget
from inference.budget import Usage

RUN = "test-run"


@pytest.fixture(autouse=True)
def _clean():
    budget.reset(RUN)
    budget.client().delete(budget._day_key("usd"))
    yield
    budget.reset(RUN)
    budget.client().delete(budget._day_key("usd"))


def usage(cost: float) -> Usage:
    return Usage(100, 50, cost, "gapgpt", "test-model")


class TestRequestCap:
    @override_settings(NEWS_MAX_PROVIDER_CALLS_PER_RUN=3)
    def test_allows_up_to_the_cap_then_refuses(self):
        assert [budget.reserve_call(RUN) for _ in range(3)] == [1, 2, 3]
        with pytest.raises(BudgetExceeded, match="request cap"):
            budget.reserve_call(RUN)

    @override_settings(NEWS_MAX_PROVIDER_CALLS_PER_RUN=50)
    def test_concurrent_workers_cannot_exceed_the_cap(self):
        """The reason this lives in Redis rather than a threading.Lock.

        Check-then-increment lets N concurrent callers all observe the last permitted
        value and all proceed, overshooting by exactly the amount of concurrency. Here 80
        callers race for 50 slots and exactly 50 win.
        """
        granted, refused = 0, 0

        def claim():
            nonlocal granted, refused
            try:
                budget.reserve_call(RUN)
            except BudgetExceeded:
                return False
            return True

        with ThreadPoolExecutor(max_workers=16) as pool:
            outcomes = list(pool.map(lambda _: claim(), range(80)))
        granted = sum(outcomes)
        refused = len(outcomes) - granted
        assert granted == 50, f"cap leaked: {granted} calls granted for a cap of 50"
        assert refused == 30

    def test_counters_are_per_run(self):
        budget.reserve_call(RUN)
        assert budget.current("another-run").run_calls == 0


class TestMoneyCeilings:
    @override_settings(NEWS_RUN_BUDGET_USD=0.01, NEWS_DAILY_BUDGET_USD=100)
    def test_run_ceiling_stops_further_calls(self):
        budget.check(RUN)  # nothing spent yet
        budget.charge(RUN, usage(0.02))
        with pytest.raises(BudgetExceeded, match="run budget"):
            budget.check(RUN)

    @override_settings(NEWS_RUN_BUDGET_USD=100, NEWS_DAILY_BUDGET_USD=0.01)
    def test_daily_ceiling_stops_further_calls(self):
        """Different failure from a runaway run: a schedule firing too often, or a retry
        storm, drifts past the day ceiling while every individual run looks fine."""
        budget.charge(RUN, usage(0.02))
        with pytest.raises(BudgetExceeded, match="daily budget"):
            budget.check(RUN)

    @override_settings(NEWS_RUN_BUDGET_USD=100, NEWS_DAILY_BUDGET_USD=100)
    def test_charges_accumulate_across_calls(self):
        budget.charge(RUN, usage(0.001))
        spend = budget.charge(RUN, usage(0.002))
        assert spend.run_usd == pytest.approx(0.003)
        assert spend.day_usd == pytest.approx(0.003)

    @override_settings(NEWS_RUN_BUDGET_USD=100, NEWS_DAILY_BUDGET_USD=100)
    def test_daily_spend_spans_runs(self):
        budget.charge(RUN, usage(0.001))
        budget.charge("other-run", usage(0.002))
        try:
            assert budget.current(RUN).day_usd == pytest.approx(0.003)
            assert budget.current(RUN).run_usd == pytest.approx(0.001)
        finally:
            budget.reset("other-run")

    @override_settings(NEWS_RUN_BUDGET_USD=1.0, NEWS_DAILY_BUDGET_USD=3.0)
    def test_remaining_is_reported_for_display(self):
        budget.charge(RUN, usage(0.25))
        spend = budget.current(RUN)
        assert spend.run_remaining == pytest.approx(0.75)
        assert spend.day_remaining == pytest.approx(2.75)


class TestAbort:
    def test_abort_is_visible_to_every_task(self):
        """A ceiling that only stops the task which noticed it is not a ceiling - the other
        200 queued articles would each rediscover it one paid call at a time."""
        assert budget.abort_reason(RUN) == ""
        budget.abort(RUN, "run budget exhausted")
        assert budget.abort_reason(RUN) == "run budget exhausted"

    def test_abort_is_scoped_to_one_run(self):
        budget.abort(RUN, "stop")
        assert budget.abort_reason("unrelated-run") == ""

    def test_reset_clears_the_abort_flag(self):
        budget.abort(RUN, "stop")
        budget.reset(RUN)
        assert budget.abort_reason(RUN) == ""
