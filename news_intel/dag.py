"""Node runtime: caching, retry taxonomy, cost accounting.

A node is a plain function wrapped in a decorator; the runtime owns everything around the
call so the node body stays readable:

    @node(name="classify", version="v4", cache_on=("content_hash", "prompt_version"))
    def classify(article, ctx): ...

Three error classes, not one. Legacy caught bare `Exception` and retried forever - 465
articles were still being re-sent every 30 minutes. Here Transient retries with backoff,
Permanent dead-letters immediately, Fatal aborts the run. The budget ceiling is enforced
here rather than trusted to callers, so a looping bug cannot spend real money overnight.
"""

from __future__ import annotations

import functools
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo

from . import config, db

TEHRAN = ZoneInfo(config.TEHRAN_TZ)


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
    """Unknown exceptions are Permanent, not Transient - retrying something you do not
    understand is how a pipeline burns money on a bug it will never recover from."""
    if isinstance(exc, NodeError):
        return type(exc)
    name = type(exc).__name__.lower()
    return Transient if any(k in name for k in ("timeout", "connection", "ssl", "socket")) else Permanent


@dataclass
class CostMeter:
    """Per-run token and money accounting, sourced from the provider's own `usage` fields."""

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
            bucket = self.by_node.setdefault(node, {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0})
            bucket["tokens_in"] += tokens_in
            bucket["tokens_out"] += tokens_out
            bucket["cost_usd"] += cost_usd

    def check(self) -> None:
        with self._lock:
            spent, budget = self.cost_usd, self.budget_usd
        if spent >= budget:
            raise BudgetExceeded(f"run budget exhausted: ${spent:.4f} of ${budget:.2f}")


@dataclass
class Ctx:
    """Everything a node needs that is not its input.

    `lock` serializes database writes across the worker pool: the connection is opened
    with check_same_thread=False, which permits cross-thread use but serializes nothing.
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

    def cache_key(self, item: Any, ctx: Ctx) -> str:
        """Key from the declared fields of the input, falling back to the context extras."""
        parts = [self.name, self.version]
        for attr in self.cache_on:
            value = getattr(item, attr, None)
            if value is None and isinstance(item, dict):
                value = item.get(attr)
            parts.append(f"{attr}={value if value is not None else ctx.extra.get(attr)}")
        return "|".join(parts)

    def cached_event(self, ctx: Ctx, key: str) -> sqlite3.Row | None:
        with ctx.lock:
            return ctx.conn.execute(
                "SELECT * FROM node_events WHERE node=? AND node_version=? AND cache_key=?"
                " AND status='success' ORDER BY id DESC LIMIT 1",
                (self.name, self.version, key),
            ).fetchone()

    def __call__(self, item: Any, ctx: Ctx, *, article_id: int | None = None) -> NodeResult:
        ctx.costs.check()
        key = self.cache_key(item, ctx) if self.cacheable else ""

        if self.cacheable and not ctx.dry_run and self.cached_event(ctx, key) is not None:
            self._emit(ctx, key, "cache_hit", article_id, attempt=0, latency_ms=0)
            return NodeResult(value=None, cached=True, attempts=0)

        for attempt in range(1, self.retries + 2):
            started = time.monotonic()
            try:
                value = self.fn(item, ctx)
            except BaseException as exc:  # noqa: BLE001 - routed by the taxonomy below
                kind = classify_exception(exc)
                latency = int((time.monotonic() - started) * 1000)
                if kind is Fatal or isinstance(exc, Fatal):
                    self._emit(ctx, key, "fatal", article_id, attempt, latency, exc)
                    raise
                if kind is Permanent:
                    self._emit(ctx, key, "permanent", article_id, attempt, latency, exc)
                    self._dead_letter(ctx, article_id, "Permanent", exc, attempt)
                    raise Permanent(str(exc)) from exc
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
            db.insert(ctx.conn, "node_events", {
                "run_id": ctx.run_id, "node": self.name, "node_version": self.version,
                "article_id": article_id, "cache_key": key, "status": status,
                "attempt": attempt, "latency_ms": latency_ms,
                "tokens_in": getattr(usage, "tokens_in", 0),
                "tokens_out": getattr(usage, "tokens_out", 0),
                "cost_usd": getattr(usage, "cost_usd", 0.0),
                "provider": getattr(usage, "provider", None),
                "model": getattr(usage, "model", None),
                "error_class": type(exc).__name__ if exc else None,
                "error": _short_error(exc), "created_at": ctx.now(),
            })

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
    return f"{type(exc).__name__}: {exc}"[:2000] if exc is not None else None


def node(**options: Any) -> Callable[[Callable[..., Any]], Node]:
    return lambda fn: Node(fn, **options)


def start_run(conn: sqlite3.Connection, run_id: str, mode: str) -> None:
    db.insert(conn, "runs", {
        "run_id": run_id, "mode": mode, "status": "running",
        "started_at": datetime.now(TEHRAN).isoformat(),
    })


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
        (status, datetime.now(TEHRAN).isoformat(), fetched, processed,
         costs.cost_usd, costs.tokens_in, costs.tokens_out, error, run_id),
    )


def new_run_id(now: datetime | None = None) -> str:
    """Sortable and unique. The random suffix is not decoration: `runs.run_id` is UNIQUE
    and second resolution is not, so two runs started in the same second collided on
    insert and took the whole run down with an IntegrityError."""
    stamp = (now or datetime.now(TEHRAN)).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{secrets.token_hex(3)}"


def invalidate(conn: sqlite3.Connection, node_name: str, *, version: str | None = None) -> int:
    """Drop cached successes for a node so the next run recomputes it (`cli replay`)."""
    clause = " AND node_version=?" if version else ""
    params = (node_name, version) if version else (node_name,)
    return conn.execute(
        f"DELETE FROM node_events WHERE node=?{clause} AND status='success'", params
    ).rowcount


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
