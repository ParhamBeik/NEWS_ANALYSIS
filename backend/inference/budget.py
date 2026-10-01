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
MONTH_KEY_TTL = 60 * 60 * 24 * 35
# Maximum charge of one reader/legacy call is far below $1 at the configured
# input/output bounds. Reserving $1 makes the month guard safe across workers.
MONTH_CALL_RESERVE_USD = 1.0

_RESERVE = """
local used = redis.call('INCR', KEYS[1])
if used == 1 then redis.call('EXPIRE', KEYS[1], ARGV[3]) end
if used > tonumber(ARGV[1]) then
  redis.call('DECR', KEYS[1])
  return -1
end
local spent = tonumber(redis.call('GET', KEYS[2]) or '0')
local reserved = tonumber(redis.call('GET', KEYS[3]) or '0')
if spent + reserved + tonumber(ARGV[4]) > tonumber(ARGV[2]) then
  redis.call('DECR', KEYS[1])
  return -2
end
redis.call('INCRBYFLOAT', KEYS[3], ARGV[4])
redis.call('EXPIRE', KEYS[3], ARGV[5])
redis.call('INCR', KEYS[4])
redis.call('EXPIRE', KEYS[4], ARGV[3])
return used
"""

_SETTLE = """
local pending = tonumber(redis.call('GET', KEYS[1]) or '0')
if pending > 0 then
  redis.call('DECR', KEYS[1])
  redis.call('INCRBYFLOAT', KEYS[2], -tonumber(ARGV[1]))
end
if ARGV[2] == 'charge' then
  local run = redis.call('INCRBYFLOAT', KEYS[3], ARGV[3])
  local day = redis.call('INCRBYFLOAT', KEYS[4], ARGV[3])
  redis.call('INCRBYFLOAT', KEYS[5], ARGV[3])
  redis.call('EXPIRE', KEYS[3], ARGV[4])
  redis.call('EXPIRE', KEYS[4], ARGV[5])
  redis.call('EXPIRE', KEYS[5], ARGV[6])
  return {run, day}
end
local calls = redis.call('DECR', KEYS[6])
if calls < 0 then redis.call('SET', KEYS[6], 0) end
return {0, 0}
"""

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


def _month_key(field: str) -> str:
    return f"newsintel:budget:month:{datetime.now(UTC):%Y%m}:{field}"


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
    cap = settings.NEWS_MAX_PROVIDER_CALLS_PER_RUN
    used = int(client().eval(
        _RESERVE, 4, _run_key(run_id, "calls"), _month_key("usd"),
        _month_key("reserved"), _run_key(run_id, "pending"),
        cap, settings.NEWS_MONTHLY_BUDGET_USD, RUN_KEY_TTL,
        MONTH_CALL_RESERVE_USD, MONTH_KEY_TTL,
    ))
    if used == -1:
        raise BudgetExceeded(f"provider request cap reached for run {run_id}: {cap}")
    if used == -2:
        raise BudgetExceeded("monthly AI budget exhausted or fully reserved")
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
    if month_spend() >= settings.NEWS_MONTHLY_BUDGET_USD:
        raise BudgetExceeded("monthly AI budget exhausted")


def charge(run_id: str, usage: Usage) -> Spend:
    """Record what a completed call actually cost, from the provider's own usage fields."""
    run_usd, day_usd = client().eval(
        _SETTLE, 6, _run_key(run_id, "pending"), _month_key("reserved"),
        _run_key(run_id, "usd"), _day_key("usd"), _month_key("usd"),
        _run_key(run_id, "calls"), MONTH_CALL_RESERVE_USD, "charge",
        usage.cost_usd, RUN_KEY_TTL, DAY_KEY_TTL, MONTH_KEY_TTL,
    )
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


def month_spend() -> float:
    return float(client().get(_month_key("usd")) or 0)


def abort_reason(run_id: str) -> str:
    return client().get(_run_key(run_id, "aborted")) or ""


def release_call(run_id: str) -> None:
    """Refund a reserved slot when the HTTP call never completed.

    Failed requests used to count against NEWS_MAX_PROVIDER_CALLS_PER_RUN, so an empty
    wallet burned the cap on 403s and then kept the guard tripped after a top-up.
    """
    client().eval(
        _SETTLE, 6, _run_key(run_id, "pending"), _month_key("reserved"),
        _run_key(run_id, "usd"), _day_key("usd"), _month_key("usd"),
        _run_key(run_id, "calls"), MONTH_CALL_RESERVE_USD, "release",
        0, RUN_KEY_TTL, DAY_KEY_TTL, MONTH_KEY_TTL,
    )


def reset(run_id: str) -> None:
    """Drop a run's counters. For tests and for restarting an aborted run deliberately."""
    conn = client()
    pending = int(conn.get(_run_key(run_id, "pending")) or 0)
    if pending:
        conn.incrbyfloat(_month_key("reserved"), -pending * MONTH_CALL_RESERVE_USD)
    conn.delete(
        _run_key(run_id, "usd"), _run_key(run_id, "calls"),
        _run_key(run_id, "pending"), _run_key(run_id, "aborted")
    )
