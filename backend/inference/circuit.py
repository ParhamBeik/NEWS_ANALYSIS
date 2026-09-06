"""Automatic halt for paid provider calls.

Not a switch an operator flips. The first empty-wallet or error-storm response opens the
circuit; crawl and image fetch keep running. A weekly probe is the only thing that may
try the provider again. Budget failures stay open until that probe sees credit — topping
up is the only fix, and retrying sooner just spends the last fractions of a cent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.actions import log_action
from core.errors import BudgetExceeded, Fatal

from .models import CircuitState, ProviderCircuit

SINGLETON_PK = 1


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    budget: bool
    detail: str


def current() -> ProviderCircuit:
    """Create the singleton already paused.

    A closed default would dispatch a full inference cycle before the first 403, which is
    the spend this exists to prevent. The weekly probe is the only path back to closed.
    """
    now = timezone.now()
    row, _ = ProviderCircuit.objects.get_or_create(
        pk=SINGLETON_PK,
        defaults={
            "state": CircuitState.OPEN_BUDGET,
            "reason": "Inference paused until a weekly probe confirms provider credit.",
            "error_kind": "budget",
            "opened_at": now,
            "next_probe_at": now + _probe_delay(),
            "last_probe_result": CircuitState.OPEN_BUDGET,
        },
    )
    return row


def snapshot() -> dict:
    row = current()
    return {
        "state": row.state,
        "reason": row.reason,
        "error_kind": row.error_kind,
        "consecutive_failures": row.consecutive_failures,
        "probe_failures": row.probe_failures,
        "opened_at": row.opened_at,
        "next_probe_at": row.next_probe_at,
        "last_probe_at": row.last_probe_at,
        "last_probe_result": row.last_probe_result,
    }


def _reclaim_stale_probing(row: ProviderCircuit) -> ProviderCircuit:
    """A crashed weekly probe must not sit in PROBING until the next Sunday tick."""
    if row.state != CircuitState.PROBING:
        return row
    if row.last_probe_at and (timezone.now() - row.last_probe_at) <= timedelta(minutes=10):
        return row
    if row.error_kind == "budget":
        row.state = CircuitState.OPEN_BUDGET
    elif row.error_kind == "probe_failed":
        row.state = CircuitState.STOPPED
    else:
        row.state = CircuitState.OPEN_ERRORS
    row.save(update_fields=["state", "updated_at"])
    return row


def block_reason() -> str:
    """Non-empty when inference must not call the provider."""
    row = _reclaim_stale_probing(current())
    if row.state == CircuitState.CLOSED:
        return ""
    if row.state == CircuitState.PROBING:
        return "weekly wallet probe in progress"
    return row.reason or row.state


def allows_inference() -> bool:
    return not block_reason()


def _probe_delay() -> timedelta:
    return timedelta(days=settings.NEWS_CIRCUIT_PROBE_DAYS)


def _open(state: str, reason: str, error_kind: str) -> ProviderCircuit:
    now = timezone.now()
    row = current()
    row.state = state
    row.reason = reason[:2000]
    row.error_kind = error_kind
    row.opened_at = row.opened_at or now
    row.next_probe_at = now + _probe_delay()
    row.last_probe_result = state
    row.save()
    log_action("circuit.open", state, kind=error_kind, next_probe=row.next_probe_at)
    return row


def open_budget(reason: str) -> ProviderCircuit:
    return _open(CircuitState.OPEN_BUDGET, reason, "budget")


def open_errors(reason: str) -> ProviderCircuit:
    return _open(CircuitState.OPEN_ERRORS, reason, "provider_error")


def close(reason: str = "wallet probe succeeded") -> ProviderCircuit:
    row = current()
    row.state = CircuitState.CLOSED
    row.reason = reason
    row.error_kind = ""
    row.consecutive_failures = 0
    row.probe_failures = 0
    row.opened_at = None
    row.next_probe_at = None
    row.last_probe_result = "closed"
    row.save()
    log_action("circuit.close", "closed", reason=reason)
    return row


def record_success() -> None:
    row = current()
    if row.consecutive_failures or row.state == CircuitState.PROBING:
        close("provider call succeeded")


def is_wallet_failure(exc: BaseException) -> bool:
    """Provider quota/auth emptiness, not a local run/day/call ceiling.

    Local ceilings reset on their own TTL. Treating them as an empty wallet pauses
    inference until the next Sunday probe even though the account still has credit.
    """
    text = f"{exc}".lower()
    if any(
        marker in text
        for marker in ("run budget exhausted", "daily budget exhausted", "request cap reached")
    ):
        return False
    return isinstance(exc, BudgetExceeded) or "quota" in text or "insufficient" in text


def record_failure(exc: BaseException) -> ProviderCircuit:
    """Open on the first wallet/auth failure; otherwise after a consecutive-error streak."""
    if is_wallet_failure(exc):
        return open_budget(str(exc))
    if isinstance(exc, BudgetExceeded):
        return current()
    current()
    ProviderCircuit.objects.filter(pk=SINGLETON_PK).update(
        consecutive_failures=F("consecutive_failures") + 1,
    )
    row = current()
    row.refresh_from_db()
    threshold = settings.NEWS_CIRCUIT_ERROR_THRESHOLD
    if isinstance(exc, Fatal) or row.consecutive_failures >= threshold:
        return open_errors(str(exc))
    log_action(
        "circuit.failure",
        "counted",
        failures=row.consecutive_failures,
        threshold=threshold,
        error=type(exc).__name__,
    )
    return row


def probe_wallet(*, live: bool) -> ProbeResult:
    """Billing GET is free. A live completion is the weekly check that can actually spend."""
    key = settings.GAPGPT_API_KEY
    if not key:
        return ProbeResult(False, True, "GAPGPT_API_KEY is empty")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        usage = requests.get(
            f"{settings.GAPGPT_BASE_URL}/dashboard/billing/usage",
            headers=headers,
            timeout=20,
        )
    except requests.RequestException as exc:
        return ProbeResult(False, False, f"usage endpoint unreachable: {exc}")

    detail = usage.text.strip()[:400]
    lowered = detail.lower()
    if usage.status_code in {401, 403} or "quota" in lowered or "insufficient" in lowered:
        return ProbeResult(False, True, detail)
    if usage.status_code >= 400:
        return ProbeResult(False, False, detail)
    if not live:
        return ProbeResult(True, False, detail[:200] or "billing ok")

    try:
        response = requests.post(
            f"{settings.GAPGPT_BASE_URL}/chat/completions",
            headers=headers,
            json={
                "model": settings.GAPGPT_MODEL,
                "messages": [{"role": "user", "content": 'Return JSON {"ok":1}'}],
                "temperature": 0,
                "max_tokens": settings.NEWS_MAX_OUTPUT_TOKENS,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
    except requests.RequestException as exc:
        return ProbeResult(False, False, f"probe request failed: {exc}")

    body = response.text[:400]
    if response.status_code == 200:
        return ProbeResult(True, False, "live probe ok")
    if "quota" in body.lower() or "insufficient" in body.lower():
        return ProbeResult(False, True, body)
    return ProbeResult(False, False, f"HTTP {response.status_code}: {body}")


def preflight() -> bool:
    """May we dispatch a batch? One billing check while closed; never a completion."""
    if not allows_inference():
        log_action("inference.preflight", "blocked", reason=block_reason())
        return False
    if not settings.NEWS_INFERENCE_PREFLIGHT:
        return True
    result = probe_wallet(live=False)
    if result.ok:
        return True
    if result.budget:
        open_budget(result.detail)
    log_action("inference.preflight", "blocked", detail=result.detail[:200])
    return False


def weekly_probe() -> dict:
    """The only scheduled path that may spend a token after the circuit has opened.

    Budget/quota stays on the free billing GET. A live completion is only for the
    error-storm reopen — topping up is the only budget fix, and a 350-token POST
    cannot create credit.
    """
    with transaction.atomic():
        row = (
            ProviderCircuit.objects.select_for_update()
            .filter(pk=SINGLETON_PK)
            .first()
        )
        if row is None:
            current()
            row = ProviderCircuit.objects.select_for_update().get(pk=SINGLETON_PK)
        row = _reclaim_stale_probing(row)
        now = timezone.now()
        if row.state == CircuitState.CLOSED:
            log_action("circuit.probe", "idle", reason="already closed")
            return {"status": CircuitState.CLOSED, "action": "none"}
        if row.state == CircuitState.PROBING:
            stale = (
                row.last_probe_at is None
                or (now - row.last_probe_at) > timedelta(minutes=10)
            )
            if not stale:
                log_action("circuit.probe", "in_progress")
                return {"status": CircuitState.PROBING, "action": "in_progress"}
        elif row.next_probe_at and now < row.next_probe_at:
            log_action("circuit.probe", "wait", next_probe=row.next_probe_at)
            return {
                "status": row.state,
                "action": "wait",
                "next_probe_at": row.next_probe_at.isoformat(),
            }

        error_kind = row.error_kind
        row.state = CircuitState.PROBING
        row.last_probe_at = now
        row.save(update_fields=["state", "last_probe_at", "updated_at"])

    live = error_kind == "provider_error"
    result = probe_wallet(live=live)
    if result.ok:
        close("weekly probe found credit")
        return {"status": CircuitState.CLOSED, "action": "reopened"}
    if result.budget or error_kind == "budget":
        open_budget(result.detail)
        return {
            "status": CircuitState.OPEN_BUDGET,
            "action": "still_empty" if result.budget else "probe_failed",
        }

    current()
    ProviderCircuit.objects.filter(pk=SINGLETON_PK).update(
        probe_failures=F("probe_failures") + 1,
    )
    row = current()
    row.refresh_from_db()
    stop_after = settings.NEWS_CIRCUIT_PROBE_FAIL_STOP
    if row.probe_failures >= stop_after:
        row.state = CircuitState.STOPPED
        row.reason = result.detail[:2000]
        row.error_kind = "probe_failed"
        row.next_probe_at = now + _probe_delay()
        row.last_probe_result = "stopped"
        row.save()
        log_action("circuit.stop", "stopped", failures=row.probe_failures)
        return {"status": CircuitState.STOPPED, "action": "stopped"}
    open_errors(result.detail)
    return {"status": CircuitState.OPEN_ERRORS, "action": "probe_failed"}
