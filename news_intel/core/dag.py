"""Node runtime: caching, retry taxonomy, cost accounting, bounded concurrency.

A node is a plain synchronous function wrapped in a decorator. The runtime owns
everything around the call so the node body stays readable:

    @node(name="classify", version="v4", cache_on=("content_hash", "prompt_version"))
    def classify(article: Article, ctx: Ctx) -> Classification:
        ...

Design notes worth knowing:

- **Caching replaces legacy `should_reprocess`.** Legacy decided what to redo by comparing
  four `*_VERSION` string constants against fields on the article
  (news_pipeline_test_version.py:2297). Same idea, made declarative and per-node: bumping
  one prompt re-runs one node rather than pushing every article through the whole pipeline.

- **Three error classes, not one.** Legacy caught bare `Exception`, marked the article
  `failed`, and `should_reprocess` then retried `failed` forever with no attempt counter -
  465 articles were still being retried every 30 minutes. Here, Transient retries with
  backoff, Permanent goes straight to the dead-letter table, and Fatal aborts the run.

- **The budget is a hard ceiling.** A bug that loops must not be able to spend real money
  overnight, so the ceiling is enforced in the runtime rather than trusted to callers.
"""

from __future__ import annotations

import functools
import secrets
import sqlite3
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

from . import config, db

TEHRAN = ZoneInfo(config.TEHRAN_TZ)


# --------------------------------------------------------------------------- errors


class NodeError(Exception):
    """Base for errors the runtime knows how to route."""


class Transient(NodeError):
    """Worth retrying: timeout, 429, 5xx, connection reset."""


class Permanent(NodeError):
    """Not worth retrying: unparseable article, schema violation after repair."""


class Fatal(NodeError):
    """Abort the run: bad credentials, budget exhausted, corrupt config."""


class BudgetExceeded(Fatal):
    pass


def classify_exception(exc: BaseException) -> type[NodeError]:
    """Map an arbitrary exception onto the taxonomy.

    Unknown exceptions are Permanent, not Transient. Retrying something you do not
    understand is how a pipeline burns money on a bug it will never recover from.
    """
    if isinstance(exc, NodeError):
        return type(exc)
    name = type(exc).__name__.lower()
    if any(k in name for k in ("timeout", "connection", "ssl", "socket")):
        return Transient
    return Permanent


# ---------------------------------------------------------------------------- cost


@dataclass
class CostMeter:
    """Per-run token and money accounting, sourced from provider `usage` fields.

    Legacy estimated tokens from character counts (`estimate_tokens:833`), so its $4.41
    lifetime figure is approximate. These numbers are the provider's own.
    """

    budget_usd: float
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    by_node: dict[str, dict[str, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def charge(self, node: str, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
        with self._lock:
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
            self.cost_usd += cost_usd
            bucket = self.by_node.setdefault(
                node, {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
            )
            bucket["tokens_in"] += tokens_in
            bucket["tokens_out"] += tokens_out
            bucket["cost_usd"] += cost_usd

    def check(self) -> None:
        with self._lock:
            spent, budget = self.cost_usd, self.budget_usd
        if spent >= budget:
            raise BudgetExceeded(f"run budget exhausted: ${spent:.4f} of ${budget:.2f}")


# ------------------------------------------------------------------------- context


@dataclass
class Ctx:
    """Everything a node needs that is not its input.

    `lock` serializes database writes across the node worker pool. The connection is
    opened with check_same_thread=False, which permits cross-thread use but provides no
    serialization of its own.
    """

    conn: sqlite3.Connection
    run_id: str
    costs: CostMeter
    providers: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def now(self) -> str:
        return datetime.now(TEHRAN).isoformat()


# ---------------------------------------------------------------------------- node


@dataclass
class NodeResult:
    value: Any
    cached: bool = False
    attempts: int = 1


class Node:
    """A wrapped pipeline step. Call it like the function it wraps."""

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        name: str,
        version: str = "v1",
        retries: int = 2,
        backoff: float = 1.0,
        cache_on: Sequence[str] = (),
        cacheable: bool = True,
    ) -> None:
        self.fn = fn
        self.name = name
        self.version = version
        self.retries = retries
        self.backoff = backoff
        self.cache_on = tuple(cache_on)
        self.cacheable = cacheable and bool(cache_on)
        functools.update_wrapper(self, fn)

    # -- cache key -----------------------------------------------------------

    def cache_key(self, item: Any, ctx: Ctx) -> str:
        """Build the key from the declared fields of the input plus the context extras."""
        parts = [self.name, self.version]
        for attr in self.cache_on:
            value = getattr(item, attr, None)
            if value is None and isinstance(item, dict):
                value = item.get(attr)
            if value is None:
                value = ctx.extra.get(attr)
            parts.append(f"{attr}={value}")
        return "|".join(parts)

    def cached_event(self, ctx: Ctx, key: str) -> sqlite3.Row | None:
        with ctx.lock:
            return ctx.conn.execute(
                "SELECT * FROM node_events WHERE node=? AND node_version=? AND cache_key=?"
                " AND status='success' ORDER BY id DESC LIMIT 1",
                (self.name, self.version, key),
            ).fetchone()

    # -- execution -----------------------------------------------------------

    def __call__(self, item: Any, ctx: Ctx, *, article_id: int | None = None) -> NodeResult:
        ctx.costs.check()
        key = self.cache_key(item, ctx) if self.cacheable else ""

        if self.cacheable and not ctx.dry_run:
            hit = self.cached_event(ctx, key)
            if hit is not None:
                self._emit(ctx, key, "cache_hit", article_id, attempt=0, latency_ms=0)
                return NodeResult(value=None, cached=True, attempts=0)

        last_exc: BaseException | None = None
        for attempt in range(1, self.retries + 2):
            started = time.monotonic()
            try:
                value = self.fn(item, ctx)
            except BaseException as exc:  # noqa: BLE001 - routed by taxonomy below
                kind = classify_exception(exc)
                latency = int((time.monotonic() - started) * 1000)
                last_exc = exc
                if kind is Fatal or isinstance(exc, Fatal):
                    self._emit(ctx, key, "fatal", article_id, attempt, latency, exc)
                    raise
                if kind is Permanent:
                    self._emit(ctx, key, "permanent", article_id, attempt, latency, exc)
                    self._dead_letter(ctx, article_id, kind.__name__, exc, attempt)
                    raise Permanent(str(exc)) from exc
                # Transient: retry unless this was the last attempt.
                if attempt == self.retries + 1:
                    self._emit(ctx, key, "exhausted", article_id, attempt, latency, exc)
                    self._dead_letter(ctx, article_id, "Transient", exc, attempt)
                    raise Transient(str(exc)) from exc
                self._emit(ctx, key, "retry", article_id, attempt, latency, exc)
                time.sleep(self.backoff * (2 ** (attempt - 1)))
                continue

            latency = int((time.monotonic() - started) * 1000)
            usage = getattr(value, "usage", None)
            if usage is not None:
                ctx.costs.charge(self.name, usage.tokens_in, usage.tokens_out, usage.cost_usd)
            self._emit(ctx, key, "success", article_id, attempt, latency, usage=usage)
            return NodeResult(value=value, cached=False, attempts=attempt)

        raise Permanent(f"{self.name} fell through retry loop: {last_exc}")

    # -- bookkeeping ---------------------------------------------------------

    def _emit(
        self,
        ctx: Ctx,
        key: str,
        status: str,
        article_id: int | None,
        attempt: int,
        latency_ms: int,
        exc: BaseException | None = None,
        usage: Any | None = None,
    ) -> None:
        if ctx.dry_run:
            return
        with ctx.lock:
            db.insert(
                ctx.conn,
                "node_events",
                {
                    "run_id": ctx.run_id,
                    "node": self.name,
                    "node_version": self.version,
                    "article_id": article_id,
                    "cache_key": key,
                    "status": status,
                    "attempt": attempt,
                    "latency_ms": latency_ms,
                    "tokens_in": getattr(usage, "tokens_in", 0),
                    "tokens_out": getattr(usage, "tokens_out", 0),
                    "cost_usd": getattr(usage, "cost_usd", 0.0),
                    "provider": getattr(usage, "provider", None),
                    "model": getattr(usage, "model", None),
                    "error_class": type(exc).__name__ if exc else None,
                    "error": _short_error(exc) if exc else None,
                    "created_at": ctx.now(),
                },
            )

    def _dead_letter(
        self, ctx: Ctx, article_id: int | None, error_class: str, exc: BaseException, attempts: int
    ) -> None:
        if ctx.dry_run or article_id is None:
            return
        with ctx.lock:
            ctx.conn.execute(
                "INSERT INTO dead_letters(article_id, node, error_class, attempts, last_error,"
                " quarantined_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(article_id, node) DO UPDATE SET"
                " attempts = attempts + excluded.attempts, last_error = excluded.last_error,"
                " error_class = excluded.error_class, quarantined_at = excluded.quarantined_at,"
                " resolved_at = NULL",
                (article_id, self.name, error_class, attempts, _short_error(exc), ctx.now()),
            )


def _short_error(exc: BaseException | None) -> str | None:
    if exc is None:
        return None
    text = f"{type(exc).__name__}: {exc}"
    return text[:2000] or traceback.format_exc()[:2000]


def node(
    *,
    name: str,
    version: str = "v1",
    retries: int = 2,
    backoff: float = 1.0,
    cache_on: Sequence[str] = (),
    cacheable: bool = True,
) -> Callable[[Callable[..., Any]], Node]:
    def wrap(fn: Callable[..., Any]) -> Node:
        return Node(
            fn,
            name=name,
            version=version,
            retries=retries,
            backoff=backoff,
            cache_on=cache_on,
            cacheable=cacheable,
        )

    return wrap


# ------------------------------------------------------------------------ mapping


@dataclass
class MapOutcome:
    results: list[Any]
    succeeded: int = 0
    cached: int = 0
    failed: int = 0
    errors: list[tuple[Any, BaseException]] = field(default_factory=list)


def map_node(
    step: Node,
    items: Iterable[Any],
    ctx: Ctx,
    *,
    workers: int = 8,
    article_id_of: Callable[[Any], int | None] = lambda _: None,
) -> MapOutcome:
    """Run a node over many items with bounded concurrency.

    Per-item failures are collected, not raised: one bad article must not abandon the
    rest of the cycle. Fatal is the exception - it propagates and stops the run, which is
    what you want for an exhausted budget or a rejected API key.
    """
    items = list(items)
    outcome = MapOutcome(results=[None] * len(items))
    if not items:
        return outcome

    def run(index: int, item: Any) -> tuple[int, Any, BaseException | None]:
        try:
            return index, step(item, ctx, article_id=article_id_of(item)), None
        except Fatal:
            raise
        except BaseException as exc:  # noqa: BLE001 - recorded per item
            return index, None, exc

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for index, result, exc in pool.map(lambda pair: run(*pair), enumerate(items)):
            if exc is not None:
                outcome.failed += 1
                outcome.errors.append((items[index], exc))
                continue
            outcome.results[index] = result.value
            if result.cached:
                outcome.cached += 1
            else:
                outcome.succeeded += 1
    return outcome


# ---------------------------------------------------------------------------- runs


def start_run(conn: sqlite3.Connection, run_id: str, mode: str) -> None:
    db.insert(
        conn,
        "runs",
        {
            "run_id": run_id,
            "mode": mode,
            "status": "running",
            "started_at": datetime.now(TEHRAN).isoformat(),
        },
    )


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    costs: CostMeter,
    *,
    status: str = "success",
    fetched: int = 0,
    processed: int = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        "UPDATE runs SET status=?, finished_at=?, articles_fetched=?, articles_processed=?,"
        " cost_usd=?, tokens_in=?, tokens_out=?, error=? WHERE run_id=?",
        (
            status,
            datetime.now(TEHRAN).isoformat(),
            fetched,
            processed,
            costs.cost_usd,
            costs.tokens_in,
            costs.tokens_out,
            error,
            run_id,
        ),
    )


def new_run_id(now: datetime | None = None) -> str:
    """Sortable, unique run identifier.

    The suffix is not decoration. `runs.run_id` is UNIQUE and second resolution is not:
    two runs started inside the same second - a manual `run` right after another, a short
    `--interval-minutes` over a small `--limit` - collided on insert and took the whole
    run down with an IntegrityError before it fetched anything.
    """
    stamp = (now or datetime.now(TEHRAN)).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{secrets.token_hex(3)}"


def invalidate(conn: sqlite3.Connection, node_name: str, *, version: str | None = None) -> int:
    """Drop cached successes for a node so the next run recomputes it.

    This is what `cli replay --node classify` uses.
    """
    if version:
        cur = conn.execute(
            "DELETE FROM node_events WHERE node=? AND node_version=? AND status='success'",
            (node_name, version),
        )
    else:
        cur = conn.execute(
            "DELETE FROM node_events WHERE node=? AND status='success'", (node_name,)
        )
    return cur.rowcount


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
