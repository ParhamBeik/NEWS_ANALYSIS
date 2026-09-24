"""Unit tests for the automatic provider halt.

The circuit is the thing that must stop spending without anyone flipping a switch, so the
tests pin the state machine rather than the HTTP client.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from core.errors import BudgetExceeded, Fatal, Transient
from inference import circuit
from inference.models import CircuitState, NodeEvent, NodeStatus, Run, RunStatus
from inference.tasks import finalize_stale_runs, run_cycle

pytestmark = pytest.mark.django_db


class TestCircuitStateMachine:
    @pytest.mark.fresh_circuit
    def test_first_row_pauses_inference_until_a_probe_confirms_credit(self):
        """A closed default would fire one full paid cycle before the first 403."""
        row = circuit.current()
        assert row.state == CircuitState.OPEN_BUDGET
        assert circuit.allows_inference() is False
        assert row.next_probe_at is not None

    def test_a_budget_error_opens_immediately_and_blocks(self):
        circuit.record_failure(BudgetExceeded("provider quota exhausted"))
        assert circuit.current().state == CircuitState.OPEN_BUDGET
        assert circuit.allows_inference() is False
        assert circuit.current().next_probe_at is not None

    def test_a_local_run_ceiling_does_not_open_the_circuit(self):
        circuit.record_failure(BudgetExceeded("run budget exhausted: $1.0000 of $1.00"))
        assert circuit.allows_inference() is True
        assert circuit.current().state == CircuitState.CLOSED

    def test_a_local_request_cap_does_not_open_the_circuit(self):
        circuit.record_failure(BudgetExceeded("provider request cap reached for run r: 1000"))
        assert circuit.allows_inference() is True

    def test_transient_errors_open_only_after_the_threshold(self, settings):
        settings.NEWS_CIRCUIT_ERROR_THRESHOLD = 3
        circuit.record_failure(Transient("429"))
        circuit.record_failure(Transient("429"))
        assert circuit.allows_inference() is True
        circuit.record_failure(Transient("429"))
        assert circuit.current().state == CircuitState.OPEN_ERRORS
        assert circuit.allows_inference() is False

    def test_a_fatal_auth_error_opens_without_waiting(self):
        circuit.record_failure(Fatal("provider authentication failed"))
        assert circuit.current().state == CircuitState.OPEN_ERRORS

    def test_weekly_probe_waits_until_next_probe_at(self):
        circuit.open_budget("empty")
        result = circuit.weekly_probe()
        assert result["action"] == "wait"
        assert circuit.current().state == CircuitState.OPEN_BUDGET

    def test_weekly_probe_keeps_budget_open_when_still_empty(self, monkeypatch):
        circuit.open_budget("empty")
        row = circuit.current()
        row.next_probe_at = timezone.now() - timedelta(minutes=1)
        row.save()
        monkeypatch.setattr(
            circuit, "probe_wallet",
            lambda *, live: circuit.ProbeResult(False, True, "still empty"),
        )
        result = circuit.weekly_probe()
        assert result["action"] == "still_empty"
        assert circuit.current().state == CircuitState.OPEN_BUDGET

    def test_weekly_probe_reopens_when_credit_returns(self, monkeypatch):
        circuit.open_budget("empty")
        row = circuit.current()
        row.next_probe_at = timezone.now() - timedelta(minutes=1)
        row.save()
        monkeypatch.setattr(
            circuit, "probe_wallet",
            lambda *, live: circuit.ProbeResult(True, False, "ok"),
        )
        result = circuit.weekly_probe()
        assert result["action"] == "reopened"
        assert circuit.allows_inference() is True

    def test_a_failed_billing_get_does_not_reclassify_a_wallet_circuit(self, monkeypatch):
        """A usage-endpoint timeout must not unlock a live completion next week."""
        circuit.open_budget("empty")
        row = circuit.current()
        row.next_probe_at = timezone.now() - timedelta(minutes=1)
        row.save()
        monkeypatch.setattr(
            circuit,
            "probe_wallet",
            lambda *, live: circuit.ProbeResult(False, False, "usage endpoint unreachable"),
        )
        circuit.weekly_probe()
        assert circuit.current().state == CircuitState.OPEN_BUDGET
        assert circuit.current().error_kind == "budget"

        row = circuit.current()
        row.next_probe_at = timezone.now() - timedelta(minutes=1)
        row.save()
        seen: list[bool] = []
        monkeypatch.setattr(
            circuit,
            "probe_wallet",
            lambda *, live: seen.append(live) or circuit.ProbeResult(False, True, "empty"),
        )
        circuit.weekly_probe()
        assert seen == [False]

    def test_weekly_probe_uses_billing_only_while_budget_is_open(self, monkeypatch):
        seen: list[bool] = []
        circuit.open_budget("empty")
        row = circuit.current()
        row.next_probe_at = timezone.now() - timedelta(minutes=1)
        row.save()
        monkeypatch.setattr(
            circuit,
            "probe_wallet",
            lambda *, live: seen.append(live) or circuit.ProbeResult(False, True, "empty"),
        )
        circuit.weekly_probe()
        assert seen == [False]

    def test_an_error_circuit_probe_is_allowed_to_spend(self, monkeypatch):
        seen: list[bool] = []
        circuit.open_errors("storm")
        row = circuit.current()
        row.next_probe_at = timezone.now() - timedelta(minutes=1)
        row.save()
        monkeypatch.setattr(
            circuit,
            "probe_wallet",
            lambda *, live: seen.append(live) or circuit.ProbeResult(True, False, "ok"),
        )
        circuit.weekly_probe()
        assert seen == [True]

    def test_a_stale_probe_reverts_to_the_prior_open_state(self):
        circuit.open_budget("empty")
        row = circuit.current()
        row.state = CircuitState.PROBING
        row.last_probe_at = timezone.now() - timedelta(minutes=11)
        row.save()
        assert circuit.allows_inference() is False
        assert circuit.current().state == CircuitState.OPEN_BUDGET

    def test_weekly_probe_skips_when_already_in_progress(self):
        circuit.open_errors("storm")
        row = circuit.current()
        row.state = CircuitState.PROBING
        row.last_probe_at = timezone.now()
        row.next_probe_at = timezone.now() - timedelta(minutes=1)
        row.save()
        assert circuit.weekly_probe()["action"] == "in_progress"


class TestRunCycleRespectsCircuit:
    def test_an_open_circuit_dispatches_nothing(self, make_article, variant, monkeypatch):
        """The 1,624-failures-an-hour loop: dispatching while the wallet is empty."""
        calls = []
        monkeypatch.setattr(
            "inference.tasks.process_article.delay",
            lambda *args: calls.append(args),
        )
        make_article()
        circuit.open_budget("provider quota exhausted")
        result = run_cycle()
        assert result["dispatched"] == 0
        assert result["status"] == "circuit_open"
        assert calls == []
        assert Run.objects.count() == 0


class TestFinalizeDoesNotMarkFailureAsSuccess:
    def test_quota_events_close_as_quota_exhausted(self):
        run = Run.objects.create(started_at=timezone.now() - timedelta(hours=1))
        NodeEvent.objects.create(
            run=run, node="classify", status=NodeStatus.QUOTA_EXHAUSTED, error="quota",
        )
        NodeEvent.objects.filter(run=run).update(
            created_at=timezone.now() - timedelta(minutes=30)
        )
        finalize_stale_runs()
        run.refresh_from_db()
        assert run.status == RunStatus.QUOTA_EXHAUSTED

    def test_a_mid_run_halt_is_not_success(self):
        """Early-return on an open circuit used to write no event, so prior successes won."""
        run = Run.objects.create(started_at=timezone.now() - timedelta(hours=1))
        NodeEvent.objects.create(run=run, node="classify", status=NodeStatus.SUCCESS)
        NodeEvent.objects.create(run=run, node="classify", status=NodeStatus.CIRCUIT_OPEN)
        NodeEvent.objects.filter(run=run).update(
            created_at=timezone.now() - timedelta(minutes=30)
        )
        finalize_stale_runs()
        run.refresh_from_db()
        assert run.status == RunStatus.CIRCUIT_OPEN

    def test_a_recovered_retry_closes_as_success(self):
        run = Run.objects.create(started_at=timezone.now() - timedelta(hours=1))
        NodeEvent.objects.create(run=run, node="classify", status=NodeStatus.RETRY)
        NodeEvent.objects.create(run=run, node="classify", status=NodeStatus.SUCCESS)
        NodeEvent.objects.filter(run=run).update(
            created_at=timezone.now() - timedelta(minutes=30)
        )
        finalize_stale_runs()
        run.refresh_from_db()
        assert run.status == RunStatus.SUCCESS


class TestProcessArticleRecordsTheHalt:
    def test_an_open_circuit_writes_a_node_event(self, make_article, variant):
        from inference.tasks import process_article

        article = make_article()
        circuit.open_budget("empty")
        result = process_article(article.pk, variant.pk, "run-circuit")
        assert result["status"] == NodeStatus.CIRCUIT_OPEN
        assert NodeEvent.objects.filter(
            run__run_id="run-circuit", status=NodeStatus.CIRCUIT_OPEN
        ).exists()

    def test_a_transient_node_is_counted_and_recorded(
        self, article, variant, monkeypatch
    ):
        from inference.tasks import _run_node

        class Fake:
            def complete(self, *args, **kwargs):
                raise Transient("503")

        variant.classify_model = "cheap-classifier"
        variant.save()
        selected = []
        monkeypatch.setattr(
            "inference.tasks.provider_for",
            lambda v, model=None: selected.append(model) or Fake(),
        )
        with pytest.raises(Transient):
            _run_node("classify", article.pk, variant.pk, "run-t", 1)
        assert selected == ["cheap-classifier"]
        assert NodeEvent.objects.get(status=NodeStatus.RETRY).model == "cheap-classifier"
        assert circuit.current().consecutive_failures >= 1

    def test_embed_quota_opens_the_circuit(self, make_article, monkeypatch):
        from inference.tasks import embed_article

        article = make_article()

        class Fake:
            def embed(self, *args, **kwargs):
                raise BudgetExceeded("provider quota exhausted (HTTP 403): remaining user quota")

        from inference import budget

        run_id = "embed-quota-test"
        budget.reset(run_id)
        monkeypatch.setattr("inference.tasks.GapGPTProvider", Fake)
        with pytest.raises(BudgetExceeded):
            embed_article.run(article.pk, run_id)
        assert circuit.current().state == CircuitState.OPEN_BUDGET
