"""Ingest and inference: quality gate -> upsert -> dedup -> classify/evaluate/summarize,
plus the rolling-window backfill that keeps the last N days complete."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import jdatetime

from . import config, dag, db, dedupe, sources, text
from .prompts import PROMPT_VERSION
from .providers import Provider, provider_identities
from .reviews import reviewed_examples
from .scoring import AXES
from .sources import RawArticle

# The LLM nodes and the table each one writes to. That table is also the "already ran?"
# gate (the nodes are cacheable=False), and what `cli replay` clears.
RESULT_TABLES = {"classify": "classifications", "evaluate": "evaluations", "summarize": "summaries"}
NODES = tuple(RESULT_TABLES)

MIN_TITLE_CHARS = 10
MIN_EVIDENCE_CHARS = 40  # title + lead is enough to judge a photo post; a body is not required
FUTURE_TOLERANCE = timedelta(hours=6)


@dataclass(frozen=True)
class Work:
    article_id: int
    article: RawArticle


# ------------------------------------------------------------------------ quality gate


def quality_reason(article, *, now: datetime | None = None) -> str | None:
    """Why this article is not worth an inference call, or None if it is.

    Every article that reaches the classifier costs a paid call, so anything the extractor
    mangled is stopped here. A reason string rather than a bool, because a gate that fires
    often is a broken parser announcing itself and /ops groups the failures by cause.
    """
    title = text.clean(article.title)
    if not title:
        return "missing_title"
    if len(title) < MIN_TITLE_CHARS:
        return "title_too_short"
    evidence = len(title) + len(text.clean(article.lead)) + len(text.clean(article.content))
    if evidence < MIN_EVIDENCE_CHARS:
        return "insufficient_text"
    published = text.parse_iso(article.published_at)
    if published is not None:
        published = published if published.tzinfo else published.replace(tzinfo=timezone.utc)
        # A future timestamp means a misparsed date, which silently breaks dedup's time
        # window and the workbook's daily grouping.
        if published > (now or datetime.now(timezone.utc)) + FUTURE_TOLERANCE:
            return "published_in_future"
    if not article.url or not article.url.startswith(("http://", "https://")):
        return "invalid_url"
    return None


# ----------------------------------------------------------------------------- ingest


def _published_fields(value: str | None) -> tuple[str | None, str | None]:
    moment = text.parse_iso(value)
    if moment is None:
        return None, None
    moment = moment.astimezone(ZoneInfo(config.TEHRAN_TZ))
    jalali = jdatetime.date.fromgregorian(year=moment.year, month=moment.month, day=moment.day)
    return text.jalali_str(jalali), moment.strftime("%H:%M")


def _is_duplicate(conn: sqlite3.Connection, article_id: int) -> bool:
    return conn.execute(
        "SELECT duplicate_of FROM articles WHERE id=?", (article_id,)
    ).fetchone()["duplicate_of"] is not None


def upsert_article(conn: sqlite3.Connection, article: RawArticle, run_id: str) -> tuple[int, bool, bool]:
    """Store or touch an article. Returns (id, newly created, is a duplicate)."""
    now = datetime.now().astimezone().isoformat()
    existing = conn.execute("SELECT id FROM articles WHERE url=?", (article.url,)).fetchone()
    if existing:
        article_id = int(existing["id"])
        conn.execute(
            "UPDATE articles SET last_seen_run=?, fetched_at=? WHERE id=?", (run_id, now, article_id)
        )
        return article_id, False, _is_duplicate(conn, article_id)

    persian_date, published_time = _published_fields(article.published_at)
    article_id = db.insert(conn, "articles", {
        "url": article.url,
        "identity_key": f"hash:{article.content_hash}",
        "source": article.source,
        "original_outlet": text.clean(article.original_outlet or "") or None,
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
        "extraction_tier": article.extraction_tier,
    })
    # Insert first, then resolve: dedup compares against stored rows, and linking may
    # decide this newer copy is the better canonical and demote the existing one - in
    # which case this row is NOT the duplicate and does need inference.
    dedupe.resolve(
        conn, article_id=article_id, title=article.title,
        content_hash=article.content_hash, published_at=article.published_at,
    )
    return article_id, True, _is_duplicate(conn, article_id)


def _already_ran(conn: sqlite3.Connection, table: str, article_id: int, provider: Provider) -> bool:
    """True if this node ran for this article/prompt under any identity `provider` could
    have answered as - a FallbackProvider may have been served by either backend."""
    return any(
        conn.execute(
            f"SELECT 1 FROM {table} WHERE article_id=? AND prompt_version=?"
            " AND provider=? AND model=? LIMIT 1",
            (article_id, PROMPT_VERSION, name, model),
        ).fetchone()
        for name, model in provider_identities(provider)
    )


def process(
    conn: sqlite3.Connection,
    articles: Iterable[RawArticle],
    provider: Provider | Mapping[str, Provider],
    *,
    run_id: str | None = None,
) -> dict[str, int]:
    """Persist article inference once per content/prompt/provider combination.

    `provider` is one provider for every node, or a node -> provider mapping. Each node
    reads its own, so a run can classify locally and evaluate on a hosted model; provider
    and model are stamped on every row and the "already done?" check is keyed on them, so
    swapping one node's model re-runs that node only.
    """
    run_id = run_id or dag.new_run_id()
    routed: Mapping[str, Provider] = (
        provider if isinstance(provider, Mapping) else {node: provider for node in NODES}
    )
    if missing := sorted(set(NODES) - set(routed)):
        raise config.ConfigError(f"no provider routed for node(s) {missing}")

    costs = dag.CostMeter(budget_usd=config.run_budget_usd())
    ctx = dag.Ctx(conn=conn, run_id=run_id, costs=costs)
    dag.start_run(conn, run_id, "pipeline")
    stats = dict.fromkeys(
        ("fetched", "new", "rejected", "duplicate", "classified", "evaluated", "summarized"), 0
    )

    # Every conn access inside a node may run from a worker thread, so each is wrapped in
    # ctx.lock: sqlite3 permits cross-thread use but does not serialize it. The provider
    # calls are deliberately left unlocked - that HTTP wait is the whole reason to
    # parallelize across articles.
    def locked(query: str, *params):
        with ctx.lock:
            return conn.execute(query, params).fetchone()

    def category_of(article_id: int) -> str:
        return locked(
            "SELECT category FROM latest_classification WHERE article_id=?", article_id
        )["category"]

    def persist(node: str, work: Work, result, **columns) -> None:
        """Write one node's answer, stamped with what produced it. The stamp is what makes
        A/B comparison possible and what the "already ran?" gate matches on."""
        with ctx.lock:
            db.insert(conn, RESULT_TABLES[node], {
                "article_id": work.article_id, **columns,
                "prompt_version": PROMPT_VERSION, "provider": result.usage.provider,
                "model": result.usage.model, "run_id": run_id, "created_at": dag.utc_now(),
            })

    @dag.node(name="classify", version=PROMPT_VERSION, cacheable=False)
    def classify(work: Work, _: dag.Ctx):
        with ctx.lock:
            examples = reviewed_examples(conn, work.article, task="classify")
        result = routed["classify"].classify(work.article, examples)
        answer = result.data
        persist(
            "classify", work, result,
            category=answer.category, confidence=answer.confidence, rationale=answer.rationale,
            memory_keywords=json.dumps(
                answer.matched_economics_keywords + answer.matched_security_keywords,
                ensure_ascii=False,
            ),
            method=routed["classify"].name,
        )
        return result

    @dag.node(name="evaluate", version=PROMPT_VERSION, cacheable=False)
    def evaluate(work: Work, _: dag.Ctx):
        category = category_of(work.article_id)
        with ctx.lock:
            examples = reviewed_examples(conn, work.article, task="evaluate", category=category)
        result = routed["evaluate"].evaluate(work.article, category, examples)
        persist("evaluate", work, result, **{
            field: getattr(result.data, field)
            for field in (*AXES, "gold_trend", "rationale")
        })
        return result

    @dag.node(name="summarize", version=PROMPT_VERSION, cacheable=False)
    def summarize(work: Work, _: dag.Ctx):
        with ctx.lock:
            examples = reviewed_examples(conn, work.article, task="summary")
        result = routed["summarize"].summarize(work.article, examples)
        persist("summarize", work, result, optimized_title=result.data.optimized_title,
                one_line=result.data.one_line)
        return result

    steps = {"classify": classify, "evaluate": evaluate, "summarize": summarize}

    def run_node(name: str, work: Work) -> bool:
        """Run a node unless its answer for this article/prompt/provider already exists."""
        with ctx.lock:
            needed = not _already_ran(conn, RESULT_TABLES[name], work.article_id, routed[name])
        if needed:
            steps[name](work, ctx, article_id=work.article_id)
        return needed

    def process_one(work: Work) -> tuple[bool, bool, bool]:
        """One article's classify -> evaluate -> summarize chain. Sequential within an
        article (evaluate needs the category classify just wrote), dispatched concurrently
        across articles - the per-node network wait is what that buys back."""
        classified = run_node("classify", work)
        if category_of(work.article_id) == "other":
            return classified, False, False
        return classified, run_node("evaluate", work), run_node("summarize", work)

    try:
        work_items = []
        for article in articles:
            stats["fetched"] += 1
            if reason := quality_reason(article):
                # Stop before paying for inference on text the extractor failed to produce.
                stats["rejected"] += 1
                article_id = upsert_article(conn, article, run_id)[0]
                conn.execute(
                    "INSERT INTO dead_letters(article_id, node, error_class, attempts,"
                    " last_error, quarantined_at) VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT(article_id, node) DO UPDATE SET"
                    " error_class=excluded.error_class, last_error=excluded.last_error,"
                    " quarantined_at=excluded.quarantined_at",
                    (article_id, "quality", reason, 1,
                     f"rejected before inference: {reason}", dag.utc_now()),
                )
                continue
            article_id, created, duplicate = upsert_article(conn, article, run_id)
            stats["new"] += int(created)
            if duplicate:
                stats["duplicate"] += 1
                continue
            work_items.append(Work(article_id, article))

        # Ingest/dedup above is inherently sequential (one article's duplicate_of decision
        # can depend on the one before it); inference below is the network-bound part.
        with ThreadPoolExecutor(max_workers=8) as pool:
            for classified, evaluated, summarized in pool.map(process_one, work_items):
                stats["classified"] += int(classified)
                stats["evaluated"] += int(evaluated)
                stats["summarized"] += int(summarized)

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


# --------------------------------------------------------------------------- backfill

# Skip re-attempting a source whose gap did not close last time, so a structurally
# unfillable gap (no article was published that day) is not hammered every cycle.
_RETRY_COOLDOWN_HOURS = 6


def ensure_window(
    conn: sqlite3.Connection, specs: dict[str, sources.SourceSpec], providers, *, days: int
) -> dict[str, int]:
    """Backfill any enabled, backfillable source with a gap in the last `days` days.

    Cheap when the window is already whole: one indexed query per source, and the (slow)
    pagination only runs when a real gap is found. Discovered articles go through the
    normal process() path, just sourced from older pages.
    """
    stats: dict[str, int] = {}
    since_date = (date.today() - timedelta(days=days - 1)).isoformat()
    now = datetime.now(timezone.utc)
    for name, spec in specs.items():
        if not spec.enabled or name not in sources.BACKFILLABLE or not db.missing_days(conn, name, days):
            continue
        last = db.get_setting(conn, f"backfill_last_run:{name}", "")
        if last and now - datetime.fromisoformat(last) < timedelta(hours=_RETRY_COOLDOWN_HOURS):
            continue
        known = {row["url"] for row in conn.execute("SELECT url FROM articles WHERE source=?", (name,))}
        found = list(sources.backfill_fetch(spec, since_date=since_date, known_urls=known))
        if found:
            process(conn, found, providers)
        with conn:
            db.set_setting(conn, f"backfill_last_run:{name}", now.isoformat())
        stats[name] = len(found)
    return stats
