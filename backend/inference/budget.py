"""Spend and request ceilings, enforced across processes.

The single-process version of this used a `threading.Lock` around an in-memory counter.
That is correct for one process and MEANINGLESS across Celery workers: four worker
processes each keep their own counter, so a $1 run budget becomes a $4 one and nothing
reports the discrepancy. Both guards therefore live in Redis atomic operations.

Three ceilings, because they fail differently:

- `run`     one runaway cycle. Aborts that run.
- `day`     slow drift - a schedule that fires too often, or a retry storm nobody noticed.
- `calls`   a runaway LOOP. This one counts REQUESTS, not money, because the failure it
            catches is a bug issuing thousands of cheap calls, which a dollar ceiling only
            notices after it has already spent the dollar.

Ordering matters and is deliberate:

- The request counter is INCREMENTED FIRST and the returned value checked. Check-then-
  increment is a race: two workers both read 999, both proceed, and the cap is exceeded by
  exactly the amount of concurrency.
- Spend is checked BEFORE a call and recorded AFTER, because the cost is not known until
  the provider reports it. The ceiling is therefore enforced to within one in-flight call
  per worker - about $0.0003 at current prices. That is a deliberate, bounded overshoot,
  not an oversight; making it exact would require reserving an estimated cost before every
  call and refunding the difference, which buys precision nobody needs at this price.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import redis
from django.conf import settings

from core.errors import BudgetExceeded

logger = logging.getLogger(__name__)

# Long enough to survive a run and be inspectable afterwards, short enough that abandoned
# run keys do not accumulate forever.
RUN_KEY_TTL = 60 * 60 * 24
DAY_KEY_TTL = 60 * 60 * 48

_client: redis.Redis | None = None


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def _today() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _run_key(run_id: str, field: str) -> str:
    return f"newsintel:budget:run:{run_id}:{field}"


def _day_key(field: str) -> str:
    return f"newsintel:budget:day:{_today()}:{field}"


@dataclass(frozen=True)
class Usage:
    tokens_in: int
    tokens_out: int
    cost_usd: float
    provider: str
    model: str


@dataclass(frozen=True)
class Spend:
    run_usd: float
    day_usd: float
    run_calls: int

    @property
    def run_remaining(self) -> float:
        return settings.NEWS_RUN_BUDGET_USD - self.run_usd

    @property
    def day_remaining(self) -> float:
        return settings.NEWS_DAILY_BUDGET_USD - self.day_usd


def current(run_id: str) -> Spend:
    """What has been spent so far. Read-only; safe to call for display."""
    conn = client()
    run_usd, day_usd, calls = conn.mget(
        _run_key(run_id, "usd"), _day_key("usd"), _run_key(run_id, "calls")
    )
    return Spend(float(run_usd or 0), float(day_usd or 0), int(calls or 0))


def reserve_call(run_id: str) -> int:
    """Claim one provider request. Raises BudgetExceeded past the cap.

    Increment-then-check, never check-then-increment: the latter lets N concurrent workers
    all observe the last permitted value and all proceed.
    """
    conn = client()
    used = conn.incr(_run_key(run_id, "calls"))
    if used == 1:
        conn.expire(_run_key(run_id, "calls"), RUN_KEY_TTL)
    cap = settings.NEWS_MAX_PROVIDER_CALLS_PER_RUN
    if used > cap:
        raise BudgetExceeded(f"provider request cap reached for run {run_id}: {cap}")
    return used


def check(run_id: str) -> None:
    """Refuse to start another call if either money ceiling is already reached."""
    spend = current(run_id)
    if spend.run_usd >= settings.NEWS_RUN_BUDGET_USD:
        raise BudgetExceeded(
            f"run budget exhausted: ${spend.run_usd:.4f} of "
            f"${settings.NEWS_RUN_BUDGET_USD:.2f}"
        )
    if spend.day_usd >= settings.NEWS_DAILY_BUDGET_USD:
        raise BudgetExceeded(
            f"daily budget exhausted: ${spend.day_usd:.4f} of "
            f"${settings.NEWS_DAILY_BUDGET_USD:.2f}"
        )


def charge(run_id: str, usage: Usage) -> Spend:
    """Record what a completed call actually cost, from the provider's own usage fields."""
    conn = client()
    pipe = conn.pipeline()
    pipe.incrbyfloat(_run_key(run_id, "usd"), usage.cost_usd)
    pipe.incrbyfloat(_day_key("usd"), usage.cost_usd)
    pipe.expire(_run_key(run_id, "usd"), RUN_KEY_TTL)
    pipe.expire(_day_key("usd"), DAY_KEY_TTL)
    run_usd, day_usd, *_ = pipe.execute()
    return Spend(float(run_usd), float(day_usd), current(run_id).run_calls)


def abort(run_id: str, reason: str) -> None:
    """Mark a run dead. Every queued task for it becomes a no-op at entry.

    A flag rather than `app.control.revoke`: revoke does not reliably reach tasks a worker
    has already prefetched, and with acks_late those are exactly the ones still to run. A
    flag every task reads costs one Redis GET and cannot be missed.
    """
    conn = client()
    conn.set(_run_key(run_id, "aborted"), reason, ex=RUN_KEY_TTL)
    logger.error("run %s aborted: %s", run_id, reason)


def day_spend() -> float:
    """Today's total, independent of any run. What /ops displays against the ceiling.

    Separate from `current()` because a dashboard has no run id, and inventing one would
    read (and TTL-touch) a key that never corresponded to a real run.
    """
    return float(client().get(_day_key("usd")) or 0)


def abort_reason(run_id: str) -> str:
    return client().get(_run_key(run_id, "aborted")) or ""


def reset(run_id: str) -> None:
    """Drop a run's counters. For tests and for restarting an aborted run deliberately."""
    conn = client()
    conn.delete(
        _run_key(run_id, "usd"), _run_key(run_id, "calls"), _run_key(run_id, "aborted")
    )
