"""Shared ingest and inference pipeline."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import jdatetime

from . import dedupe, quality
from .core import config, dag, db, normalize
from .prompts import PROMPT_VERSION
from .providers import Provider
from .reviews import reviewed_examples
from .sources import RawArticle

CLASSIFY_VERSION = PROMPT_VERSION
EVALUATE_VERSION = PROMPT_VERSION
SUMMARIZE_VERSION = PROMPT_VERSION


@dataclass(frozen=True)
class Work:
    article_id: int
    article: RawArticle
    prompt_version: str

    @property
    def content_hash(self) -> str:
        return self.article.content_hash


def _published_fields(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo(config.TEHRAN_TZ))
        date = jdatetime.date.fromgregorian(year=moment.year, month=moment.month, day=moment.day)
        return f"{date.year:04d}-{date.month:02d}-{date.day:02d}", moment.strftime("%H:%M")
    except ValueError:
        return None, None


def upsert_article(conn: sqlite3.Connection, article: RawArticle, run_id: str) -> tuple[int, bool, bool]:
    row = conn.execute("SELECT id FROM articles WHERE url=?", (article.url,)).fetchone()
    now = datetime.now().astimezone().isoformat()
    if row:
        conn.execute("UPDATE articles SET last_seen_run=?, fetched_at=? WHERE id=?", (run_id, now, row["id"]))
        duplicate = conn.execute("SELECT duplicate_of FROM articles WHERE id=?", (row["id"],)).fetchone()["duplicate_of"] is not None
        return int(row["id"]), False, duplicate
    persian_date, published_time = _published_fields(article.published_at)
    article_id = db.insert(
        conn,
        "articles",
        {
            "url": article.url,
            "identity_key": f"hash:{article.content_hash}",
            "source": article.source,
            "original_outlet": normalize.clean(article.original_outlet) or None,
            "original_title": article.title,
            "lead": article.lead,
            "content": article.content,
            "content_hash": article.content_hash,
            "published_at_gregorian": article.published_at,
            "published_at_persian": persian_date,
            "published_time": published_time,
            "date_uncertain": int(article.date_uncertain),
            "fetched_at": now,
            "first_seen_run": run_id,
            "last_seen_run": run_id,
            "extraction_tier": getattr(article, "extraction_tier", "css"),
        },
    )
    # Insert first, then resolve: dedupe compares against stored rows, and linking may
    # decide this newer copy is the better canonical and demote the existing one.
    match = dedupe.resolve(
        conn,
        article_id=article_id,
        title=article.title,
        content_hash=article.content_hash,
        published_at=article.published_at,
    )
    is_duplicate = bool(
        conn.execute(
            "SELECT duplicate_of FROM articles WHERE id=?", (article_id,)
        ).fetchone()["duplicate_of"]
    )
    if match is not None and not is_duplicate:
        # This copy won canonical status; the story itself is not new work.
        return article_id, True, False
    return article_id, True, is_duplicate


def _exists(conn: sqlite3.Connection, table: str, article_id: int, version: str, provider: Provider) -> bool:
    return bool(conn.execute(
        f"SELECT 1 FROM {table} WHERE article_id=? AND prompt_version=? AND provider=? AND model=? LIMIT 1",
        (article_id, version, provider.name, provider.model),
    ).fetchone())


def process(
    conn: sqlite3.Connection,
    articles: Iterable[RawArticle],
    provider: Provider | Mapping[str, Provider],
    *,
    run_id: str | None = None,
) -> dict[str, int]:
    """Persist article inference once per content/version/provider combination.

    `provider` is either one provider for every node, or a node -> provider mapping from
    routing.py. Each node reads its own, so a run can classify on a local model and
    evaluate on a hosted one; the provider and model are stamped on every row either way,
    and the per-node existence check is keyed on them, so switching a single node's model
    re-runs that node only.
    """
    run_id = run_id or dag.new_run_id()
    nodes: Mapping[str, Provider] = (
        provider if isinstance(provider, Mapping)
        else {name: provider for name in ("classify", "evaluate", "summarize")}
    )
    missing = {"classify", "evaluate", "summarize"} - set(nodes)
    if missing:
        raise config.ConfigError(f"no provider routed for node(s) {sorted(missing)}")
    classifier, evaluator, summarizer = nodes["classify"], nodes["evaluate"], nodes["summarize"]
    costs = dag.CostMeter(budget_usd=config.run_budget_usd())
    ctx = dag.Ctx(conn=conn, run_id=run_id, costs=costs)
    dag.start_run(conn, run_id, "pipeline")
    stats = {
        "fetched": 0, "new": 0, "rejected": 0, "duplicate": 0,
        "classified": 0, "evaluated": 0, "summarized": 0,
    }

    @dag.node(name="classify", version=CLASSIFY_VERSION, cacheable=False)
    def classify(work: Work, _: dag.Ctx):
        result = classifier.classify(work.article, reviewed_examples(conn, work.article, task="classify"))
        db.insert(conn, "classifications", {
            "article_id": work.article_id, "category": result.data.category,
            "confidence": result.data.confidence, "rationale": result.data.rationale,
            "memory_keywords": json.dumps(result.data.matched_economics_keywords + result.data.matched_security_keywords, ensure_ascii=False),
            "method": classifier.name, "prompt_version": CLASSIFY_VERSION, "provider": classifier.name,
            "model": classifier.model, "run_id": run_id, "created_at": dag.utc_now(),
        })
        return result

    @dag.node(name="evaluate", version=EVALUATE_VERSION, cacheable=False)
    def evaluate(work: Work, _: dag.Ctx):
        category = conn.execute(
            "SELECT category FROM latest_classification WHERE article_id=?", (work.article_id,)
        ).fetchone()["category"]
        result = evaluator.evaluate(work.article, category, reviewed_examples(conn, work.article, task="evaluate", category=category))
        db.insert(conn, "evaluations", {
            "article_id": work.article_id,
            **{key: getattr(result.data, key) for key in ("confidence_occurrence", "gold_price_impact", "security_relevance", "gold_trend", "rationale")},
            "prompt_version": EVALUATE_VERSION, "provider": evaluator.name, "model": evaluator.model,
            "run_id": run_id, "created_at": dag.utc_now(),
        })
        return result

    @dag.node(name="summarize", version=SUMMARIZE_VERSION, cacheable=False)
    def summarize(work: Work, _: dag.Ctx):
        result = summarizer.summarize(work.article, reviewed_examples(conn, work.article, task="summary"))
        db.insert(conn, "summaries", {
            "article_id": work.article_id, "optimized_title": result.data.optimized_title,
            "one_line": result.data.one_line, "prompt_version": SUMMARIZE_VERSION,
            "provider": summarizer.name, "model": summarizer.model, "run_id": run_id, "created_at": dag.utc_now(),
        })
        return result

    try:
        for article in articles:
            stats["fetched"] += 1
            verdict = quality.check(article)
            if not verdict.ok:
                # Stop here rather than pay for an inference call on text the extractor
                # failed to produce. The reason is recorded so the dashboard can show
                # which source is degrading and why.
                stats["rejected"] += 1
                logged = upsert_article(conn, article, run_id)[0]
                conn.execute(
                    "INSERT INTO dead_letters(article_id, node, error_class, attempts,"
                    " last_error, quarantined_at) VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT(article_id, node) DO UPDATE SET"
                    " error_class=excluded.error_class, last_error=excluded.last_error,"
                    " quarantined_at=excluded.quarantined_at",
                    (logged, "quality", verdict.reason, 1,
                     f"rejected before inference: {verdict.reason}", dag.utc_now()),
                )
                continue
            article_id, created, duplicate = upsert_article(conn, article, run_id)
            stats["new"] += int(created)
            if duplicate:
                stats["duplicate"] += 1
                continue
            work = Work(article_id, article, CLASSIFY_VERSION)
            if not _exists(conn, "classifications", article_id, CLASSIFY_VERSION, classifier):
                classify(work, ctx, article_id=article_id)
                stats["classified"] += 1
            category = conn.execute(
                "SELECT category FROM latest_classification WHERE article_id=?", (article_id,)
            ).fetchone()["category"]
            if category != "other" and not _exists(conn, "evaluations", article_id, EVALUATE_VERSION, evaluator):
                evaluate(work, ctx, article_id=article_id)
                stats["evaluated"] += 1
            if category != "other" and not _exists(conn, "summaries", article_id, SUMMARIZE_VERSION, summarizer):
                summarize(work, ctx, article_id=article_id)
                stats["summarized"] += 1
        dag.finish_run(conn, run_id, costs, fetched=stats["fetched"], processed=stats["classified"])
    except BaseException as exc:
        dag.finish_run(conn, run_id, costs, status="failed", fetched=stats["fetched"], error=str(exc))
        raise
    return stats


def set_source_health(conn: sqlite3.Connection, name: str, *, ok: bool, error: str | None = None) -> None:
    conn.execute(
        "INSERT INTO sources(name,tier,health_status,last_success_at,last_error) VALUES(?,?,?,?,?)"
        " ON CONFLICT(name) DO UPDATE SET health_status=excluded.health_status,"
        " last_success_at=excluded.last_success_at,last_error=excluded.last_error",
        (name, 1, "healthy" if ok else "degraded", dag.utc_now() if ok else None, error),
    )
