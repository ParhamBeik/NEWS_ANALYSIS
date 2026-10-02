"""Inference orchestration.

One Celery task per (article, variant): `process_article`, which walks
classify -> evaluate -> summarize in order. The nodes are functions (`_run_node`), not
tasks, and that is deliberate - making each a task and calling them from `process_article`
nests Celery's retry inside Celery's retry, so three attempts become nine HTTP calls and
nine budget charges for one logical inference. Retrying the whole chain is cheap instead of
wasteful because `_already_answered` skips whatever succeeded last time, so a summary
failing never discards a classification that was already paid for.

The three-class error taxonomy maps onto Celery like this:

- `Transient`  autoretry with exponential backoff
- `Permanent`  no retry, DeadLetter row written, task returns
- `Fatal`      no retry, the RUN is marked aborted in Redis, and every task still queued
               for it returns immediately at entry

That last one is the point of `budget.abort`. A budget ceiling that only stops the task
that noticed it is not a ceiling - the other 200 queued articles would each discover it
one paid call at a time.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from articles.models import (
    Article,
    ArticleStance,
    EventAssessment,
    EventReview,
    NewsEvent,
    UrlStatus,
    WatchItem,
)
from core.actions import log_action
from core.errors import BudgetExceeded, Fatal, Permanent, Transient
from core.ops import failure_kind, record_ai_failure
from core.vocabulary import AXES, EVENT_CATEGORIES

from . import budget, circuit, memory
from .jev import configured as jev_configured
from .models import (
    Classification,
    DeadLetter,
    Evaluation,
    NodeEvent,
    NodeStatus,
    PromptVariant,
    Run,
    RunStatus,
    Summary,
)
from .prompts import TASK_FOR_NODE, TASKS, messages
from .providers import GapGPTProvider, provider_for

logger = logging.getLogger(__name__)

RESULT_MODELS = {"classify": Classification, "evaluate": Evaluation, "summarize": Summary}


@shared_task(
    name="inference.assess_event",
    bind=True,
    autoretry_for=(Transient,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def assess_event(self, event_id: int) -> dict:
    """Fast event assessment, independent of the legacy 30-minute analyst pipeline."""
    from core.watch import shortlist, tag_event

    from .jev import decide, watch_tags

    event = NewsEvent.objects.select_related("primary_article__source").filter(pk=event_id).first()
    if event is None:
        return {"status": "missing"}
    article = event.primary_article
    evidence = "\n".join((article.original_title, article.lead, article.content[:5000]))
    digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
    if event.assessments.filter(evidence_hash=digest).exists():
        return {"status": "already_assessed", "event": event_id}
    if not jev_configured():
        return {"status": "unassessed", "reason": "provider_not_configured"}
    run_id = f"event-{event_id}"
    event_time = event.event_time
    from core.events import kept_apart

    candidates = {
        f"event_{row.id}": f"Same occurrence: {row.primary_article.original_title[:180]}"
        for row in NewsEvent.objects.filter(
            event_time__range=(event_time - timedelta(hours=36), event_time + timedelta(hours=36))
        )
        .exclude(pk=event_id)
        .exclude(pk__in=kept_apart(event_id))
        .select_related("primary_article")
        .order_by("-event_time")[:10]
    }
    try:
        response = decide(
            {
                "title": article.original_title,
                "lead": article.lead,
                "body": article.content[:5000],
                "source": article.source.display_name or article.source_id,
                "native_category": article.native_category,
            },
            run_id,
            candidates,
            shortlist(evidence, WatchItem.objects.filter(enabled=True)),
        )
    except BudgetExceeded:
        record_ai_failure("jev", "budget")
        return {"status": "unassessed", "reason": "budget_or_credits"}
    except (Fatal, Permanent, Transient) as exc:
        record_ai_failure("jev", failure_kind(exc))
        if isinstance(exc, Transient):
            raise
        logger.warning("event assessment unavailable for %s: %s", event_id, exc)
        return {"status": "unassessed", "reason": type(exc).__name__}
    answers = response["answers"]

    def score(name):
        value = float(answers[name]["score"])
        if not 0 <= value <= 4:
            raise ValueError("score outside Jev's 0-4 range")
        return round(value * 25)

    try:
        category = answers["category"]["choice"]
        if category not in EVENT_CATEGORIES:
            raise KeyError("category")
        iran_score, global_score = score("iran"), score("global")
        asset_scores = {
            key: score(f"asset_{key}")
            for key in (
                "fx",
                "gold",
                "tehran_index",
                "oil",
                "bitcoin",
            )
        }
        confidence = min(
            float(answers[name].get("confidence", 0))
            for name in (
                "category",
                "iran",
                "global",
            )
        )
        if not 0 <= confidence <= 1:
            raise ValueError("confidence outside 0-1 range")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("invalid Jev answer for event %s: %s", event_id, exc)
        record_ai_failure("jev", "invalid_answer")
        return {"status": "unassessed", "reason": "invalid_answer"}
    matched = answers.get("same_event", {})
    choice = matched.get("choice", "none")
    try:
        match_probability = float(matched.get("probabilities", {}).get(choice, 0))
    except (TypeError, ValueError):
        match_probability = 0
    merged = False
    if choice in candidates and 0.9 <= match_probability <= 1:
        from core.events import merge_events

        joining = list(event.articles.values_list("id", flat=True))
        event = merge_events(int(choice.removeprefix("event_")), event_id)
        merged = event.id != event_id
        event_id = event.id
        if merged:
            from .jev import stance

            label, stance_confidence = stance(answers)
            for article_id in joining:
                ArticleStance.objects.update_or_create(
                    event=event, article_id=article_id,
                    defaults={"stance": label, "confidence": stance_confidence},
                )
    EventAssessment.objects.create(
        event=event,
        model=str(response.get("model") or "jev"),
        evidence_hash=digest,
        category=category,
        iran_score=iran_score,
        global_score=global_score,
        asset_scores=asset_scores,
        confidence=confidence,
        cost_usd=float((response.get("usage") or {}).get("cost") or 0),
    )
    NewsEvent.objects.filter(pk=event_id).update(
        category=category,
        iran_score=iran_score,
        global_score=global_score,
        assessment_confidence=confidence,
    )
    tag_event(event, watch_tags(answers))
    from core.events import refresh_event

    refresh_event(event)
    if (max(iran_score, global_score) >= 60 and confidence < 0.7) or event_id % 20 == 0:
        EventReview.objects.get_or_create(
            event=event,
            defaults={"reason": "high_impact_uncertain" if confidence < 0.7 else "audit_sample"},
        )
    from core.tiers import brief_eligible
    from core.watch import watched_events

    if (
        brief_eligible(
            category, iran_score, global_score, watched=bool(watched_events([event_id]))
        )
        and len(evidence.strip()) >= 40
    ):
        summarize_event.delay(event_id)
    elif category != "other":
        transaction.on_commit(lambda event_id=event_id: translate_event_title.delay(event_id))
    if settings.NEWS_ALERTS_ENABLED:
        from accounts.tasks import fan_out_event
        from articles.tasks import alert_event

        alert_event.apply_async(args=[event_id], countdown=30)
        fan_out_event.apply_async(args=[event_id], kwargs={"merged": merged}, countdown=30)
    return {"status": "assessed", "event": event_id}


@shared_task(
    name="inference.summarize_event",
    bind=True,
    autoretry_for=(Transient,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def summarize_event(self, event_id: int) -> dict:
    from .jev import brief

    event = NewsEvent.objects.select_related("primary_article").filter(pk=event_id).first()
    if event is None or event.brief_fa:
        return {"status": "skipped"}
    article = event.primary_article
    supporting = [
        {
            "source": other.source.display_name or other.source_id,
            "title": other.original_title,
            "lead": other.lead[:700],
        }
        for other in event.articles.exclude(pk=article.pk).select_related("source")[:3]
    ]
    try:
        result = brief(
            {
                "title": article.original_title,
                "lead": article.lead,
                "body": article.content[:5000],
                "source": article.source.display_name or article.source_id,
                "supporting_sources": supporting,
            },
            f"event-{event_id}",
        )
    except BudgetExceeded:
        record_ai_failure("brief", "budget")
        return {"status": "unassessed", "reason": "budget_or_credits"}
    except (Fatal, Permanent, Transient) as exc:
        record_ai_failure("brief", failure_kind(exc))
        if isinstance(exc, Transient):
            raise
        logger.warning("event brief unavailable for %s: %s", event_id, exc)
        return {"status": "unassessed", "reason": type(exc).__name__}
    NewsEvent.objects.filter(pk=event_id).update(**result)
    return {"status": "summarized", "event": event_id}


@shared_task(
    name="inference.translate_event_title",
    bind=True,
    autoretry_for=(Transient,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=2,
)
def translate_event_title(self, event_id: int) -> dict:
    """Headline in the other UI language for an event without a brief (one cheap call)."""
    from articles.models import TitleTranslation

    from .jev import translate_title

    event = (
        NewsEvent.objects.select_related("primary_article__source").filter(pk=event_id).first()
    )
    if event is None or event.category in {"", "other"} or event.brief_fa:
        return {"status": "skipped"}
    article = event.primary_article
    language = "fa" if article.source.language == "en" else "en"
    cached = TitleTranslation.objects.filter(
        article=article, language=language, source_title=article.original_title
    ).first()
    if cached is None:
        try:
            text, model = translate_title(article.original_title, language, f"event-{event_id}")
        except BudgetExceeded:
            record_ai_failure("title", "budget")
            return {"status": "skipped", "reason": "budget_or_credits"}
        except (Fatal, Permanent, Transient) as exc:
            record_ai_failure("title", failure_kind(exc))
            if isinstance(exc, Transient):
                raise
            return {"status": "skipped", "reason": type(exc).__name__}
        cached, _ = TitleTranslation.objects.update_or_create(
            article=article,
            defaults={"language": language, "source_title": article.original_title,
                      "title": text, "model": model},
        )
    # A brief written meanwhile owns the titles; never overwrite it.
    NewsEvent.objects.filter(pk=event_id, brief_fa="").update(**{f"title_{language}": cached.title})
    return {"status": "translated", "event": event_id, "language": language}


@shared_task(name="inference.build_storylines")
def build_storylines() -> dict:
    """Nightly: link recent events into storylines; naming degrades to derived names."""
    from core.storylines import build

    from .jev import storyline_name

    run_id = f"storylines-{timezone.now():%Y%m%d}"

    def namer(titles):
        return storyline_name(titles, run_id) if settings.GAPGPT_API_KEY else None

    return build(namer=namer)


@shared_task(name="inference.assess_pending_events")
def assess_pending_events(limit: int = 200) -> dict:
    """Retry unassessed events after outages or credit top-ups."""
    if not jev_configured() or budget.month_spend() >= settings.NEWS_MONTHLY_BUDGET_USD:
        return {"queued": 0, "status": "provider_or_budget_unavailable"}
    ids = list(
        NewsEvent.objects.exclude(category="other")
        .filter(
            primary_article__prefilter_reason="",
            primary_article__quality_flag="",
            assessments__isnull=True,
        )
        .order_by("-event_time")
        .values_list("id", flat=True)[:limit]
    )
    for event_id in ids:
        assess_event.delay(event_id)
    return {"queued": len(ids)}


# ------------------------------------------------------------------------------ helpers


def _already_answered(node: str, article_id: int, variant: PromptVariant) -> bool:
    """Has THIS variant, under its current identity, already answered this node?

    Keyed on the variant AND its identity (see `InferenceResultQuerySet.for_variant`), so
    re-pointing a variant at a new model re-runs it, an unchanged variant costs nothing on
    a repeat cycle, and a second arm that happens to share the first arm's model is still
    asked its own question.
    """
    return (
        RESULT_MODELS[node]
        .objects.for_variant(variant, node=node)
        .filter(article_id=article_id)
        .exists()
    )


def _record(
    run: Run,
    node: str,
    article_id: int | None,
    variant: PromptVariant | None,
    status: str,
    *,
    attempt: int = 1,
    latency_ms: int | None = None,
    usage=None,
    exc: BaseException | None = None,
) -> None:
    NodeEvent.objects.create(
        run=run,
        node=node,
        article_id=article_id,
        variant=variant,
        status=status,
        attempt=attempt,
        latency_ms=latency_ms,
        tokens_in=getattr(usage, "tokens_in", 0),
        tokens_out=getattr(usage, "tokens_out", 0),
        cost_usd=getattr(usage, "cost_usd", 0),
        provider=getattr(usage, "provider", "") or (variant.provider if variant else ""),
        model=getattr(usage, "model", "") or (variant.model_for_node(node) if variant else ""),
        error_class=type(exc).__name__ if exc else "",
        error=(f"{exc}"[:2000] if exc else ""),
    )


def _dead_letter(article_id: int, node: str, exc: BaseException, attempts: int) -> None:
    DeadLetter.objects.update_or_create(
        article_id=article_id,
        node=node,
        defaults={
            "error_class": type(exc).__name__,
            "attempts": attempts,
            "last_error": f"{exc}"[:2000],
            "resolved_at": None,
        },
    )


def _run_for(run_id: str) -> Run:
    run, _ = Run.objects.get_or_create(run_id=run_id, defaults={"mode": "pipeline"})
    return run


def _context(article, variant, node: str, category: str | None):
    """Everything the prompt needs beyond the article itself."""
    task = TASK_FOR_NODE[node]
    examples = memory.retrieve(article, variant, task, category)
    market = (
        memory.market_context(article) if variant.memory_strategy == "semantic+market" else None
    )
    extra = {"category": category} if category else {}
    return messages(
        task,
        title=article.original_title,
        lead=article.lead,
        content=article.content,
        outlet=article.original_outlet or article.source_id,
        examples=examples,
        market=market,
        **extra,
    )


# -------------------------------------------------------------------------- inference


def _halt_status(reason: str) -> str:
    lowered = reason.lower()
    if "quota" in lowered or "budget" in lowered:
        return NodeStatus.QUOTA_EXHAUSTED
    if "circuit" in lowered:
        return NodeStatus.CIRCUIT_OPEN
    return NodeStatus.ABORTED


def _run_node(node: str, article_id: int, variant_id: int, run_id: str, attempt: int) -> dict:
    """Shared body for all three inference nodes."""
    if reason := circuit.block_reason():
        run = _run_for(run_id)
        _record(run, node, article_id, None, NodeStatus.CIRCUIT_OPEN, attempt=attempt)
        log_action("inference.node", NodeStatus.CIRCUIT_OPEN, node=node, article=article_id)
        return {
            "article": article_id,
            "node": node,
            "status": NodeStatus.CIRCUIT_OPEN,
            "reason": reason,
        }
    if reason := budget.abort_reason(run_id):
        run = _run_for(run_id)
        status = _halt_status(reason)
        _record(run, node, article_id, None, status, attempt=attempt)
        log_action("inference.node", status, node=node, article=article_id, reason=reason[:200])
        return {"article": article_id, "node": node, "status": status, "reason": reason}

    variant = PromptVariant.objects.filter(pk=variant_id).first()
    if variant is None:
        raise Permanent(f"no prompt variant {variant_id}")
    article = Article.objects.filter(pk=article_id).first()
    if article is None:
        raise Permanent(f"no article {article_id}")

    run = _run_for(run_id)
    if _already_answered(node, article_id, variant):
        _record(run, node, article_id, variant, NodeStatus.SKIPPED)
        return {"article": article_id, "node": node, "status": "skipped"}

    category = None
    if node in {"evaluate"}:
        latest = (
            Classification.objects.for_variant(variant)
            .filter(article_id=article_id)
            .order_by("-created_at", "-id")
            .values_list("category", flat=True)
            .first()
        )
        if latest is None:
            raise Permanent(f"article {article_id} must be classified before evaluation")
        category = latest

    node_model = variant.model_for_node(node)
    provider = provider_for(variant, model=node_model)
    schema = TASKS[TASK_FOR_NODE[node]][0]

    started = timezone.now()
    try:
        answer = provider.complete(_context(article, variant, node, category), schema, run_id)
    except BudgetExceeded as exc:
        if circuit.is_wallet_failure(exc):
            circuit.open_budget(str(exc))
            Run.objects.filter(run_id=run_id).update(
                status=RunStatus.QUOTA_EXHAUSTED, finished_at=timezone.now(), error=str(exc)[:2000]
            )
        else:
            Run.objects.filter(run_id=run_id).update(
                status=RunStatus.ABORTED, finished_at=timezone.now(), error=str(exc)[:2000]
            )
        budget.abort(run_id, str(exc))
        node_status = (
            NodeStatus.QUOTA_EXHAUSTED if circuit.is_wallet_failure(exc) else NodeStatus.ABORTED
        )
        _record(run, node, article_id, variant, node_status, attempt=attempt, exc=exc)
        log_action("inference.node", node_status, node=node, article=article_id)
        raise
    except Fatal as exc:
        circuit.record_failure(exc)
        budget.abort(run_id, str(exc))
        Run.objects.filter(run_id=run_id).update(
            status=RunStatus.ABORTED, finished_at=timezone.now(), error=str(exc)[:2000]
        )
        _record(run, node, article_id, variant, NodeStatus.FATAL, attempt=attempt, exc=exc)
        log_action("inference.node", NodeStatus.FATAL, node=node, article=article_id)
        raise
    except Permanent as exc:
        _record(run, node, article_id, variant, NodeStatus.PERMANENT, attempt=attempt, exc=exc)
        _dead_letter(article_id, node, exc, attempt)
        log_action("inference.node", NodeStatus.PERMANENT, node=node, article=article_id)
        return {"article": article_id, "node": node, "status": "permanent", "error": str(exc)}
    except Transient as exc:
        circuit.record_failure(exc)
        _record(run, node, article_id, variant, NodeStatus.RETRY, attempt=attempt, exc=exc)
        log_action("inference.node", NodeStatus.RETRY, node=node, article=article_id)
        raise

    latency_ms = int((timezone.now() - started).total_seconds() * 1000)
    _persist(node, article, variant, run, answer)
    circuit.record_success()
    _record(
        run,
        node,
        article_id,
        variant,
        NodeStatus.SUCCESS,
        attempt=attempt,
        latency_ms=latency_ms,
        usage=answer.usage,
    )
    return {
        "article": article_id,
        "node": node,
        "status": "ok",
        "cost_usd": answer.usage.cost_usd,
    }


def _persist(node: str, article, variant: PromptVariant, run: Run, answer) -> None:
    """Write the answer, stamped with what produced it. The stamp is what makes A/B
    comparison possible and what the already-answered gate matches on."""
    data = answer.data
    common = {
        "article": article,
        "variant": variant,
        "prompt_version": variant.prompt_version,
        "provider": answer.usage.provider,
        "model": answer.usage.model,
        "run": run,
        "rationale": getattr(data, "rationale", ""),
    }
    if node == "classify":
        Classification.objects.create(
            **common,
            category=data.category,
            confidence=data.confidence,
            matched_keywords=(data.matched_economics_keywords + data.matched_security_keywords),
        )
    elif node == "evaluate":
        Evaluation.objects.create(
            **common,
            **{axis: getattr(data, axis) for axis in AXES},
            gold_trend=data.gold_trend,
        )
    else:
        Summary.objects.create(
            **{k: v for k, v in common.items() if k != "rationale"},
            optimized_title=data.optimized_title,
            one_line=data.one_line,
        )


@shared_task(
    bind=True,
    name="inference.process_article",
    autoretry_for=(Transient,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def process_article(self, article_id: int, variant_id: int, run_id: str) -> dict:
    """One article's classify -> evaluate -> summarize chain.

    Sequential within an article because evaluate needs the category classify just wrote.
    Articles classified `other` stop here: they are not scored and not summarised, which is
    where most of the saving in this pipeline actually comes from.

    This task - not the individual nodes - is the RETRY UNIT. Calling the per-node tasks
    from here would nest Celery's retry inside Celery's retry and compound to nine calls
    for one logical inference, which is the bug this codebase has already paid for once.
    Retrying the whole chain is cheap instead of wasteful because `_already_answered`
    skips any node that succeeded on the previous attempt.
    """
    attempt = self.request.retries + 1
    if reason := circuit.block_reason():
        run = _run_for(run_id)
        _record(run, "classify", article_id, None, NodeStatus.CIRCUIT_OPEN, attempt=attempt)
        log_action("inference.process", NodeStatus.CIRCUIT_OPEN, article=article_id)
        return {
            "article": article_id,
            "status": NodeStatus.CIRCUIT_OPEN,
            "reason": reason,
            "category": None,
            "steps": [],
        }

    settled_ok = {"ok", "skipped"}
    steps = [_run_node("classify", article_id, variant_id, run_id, attempt)]
    classify_status = steps[0].get("status")
    if classify_status not in settled_ok:
        log_action("inference.process", classify_status, article=article_id)
        return {
            "article": article_id,
            "status": classify_status,
            "category": None,
            "steps": steps,
        }

    category = (
        Classification.objects.for_variant(PromptVariant.objects.get(pk=variant_id))
        .filter(article_id=article_id)
        .order_by("-created_at", "-id")
        .values_list("category", flat=True)
        .first()
    )
    if category and category != "other":
        steps.append(_run_node("evaluate", article_id, variant_id, run_id, attempt))
        if steps[-1].get("status") in settled_ok:
            steps.append(_run_node("summarize", article_id, variant_id, run_id, attempt))

    overall = "ok"
    for step in steps:
        if step.get("status") not in settled_ok:
            overall = step["status"]
            break
    log_action("inference.process", overall, article=article_id, category=category)
    return {"article": article_id, "status": overall, "category": category, "steps": steps}


@shared_task(
    name="inference.embed_article",
    autoretry_for=(Transient,),
    retry_backoff=True,
    max_retries=3,
)
def embed_article(article_id: int, run_id: str = "embeddings") -> dict:
    """Compute and store one article's embedding."""
    if reason := circuit.block_reason():
        log_action("inference.embed", NodeStatus.CIRCUIT_OPEN, article=article_id)
        return {"article": article_id, "status": NodeStatus.CIRCUIT_OPEN, "reason": reason}
    if budget.abort_reason(run_id):
        return {"article": article_id, "status": "aborted"}
    article = Article.objects.filter(pk=article_id).first()
    if article is None:
        raise Permanent(f"no article {article_id}")
    text = memory.embedding_text(article)
    if not text:
        return {"article": article_id, "status": "empty"}
    model = settings.GAPGPT_EMBEDDING_MODEL
    try:
        vectors, _ = GapGPTProvider().embed([text], run_id, model=model)
    except BudgetExceeded as exc:
        if circuit.is_wallet_failure(exc):
            circuit.open_budget(str(exc))
            log_action("inference.embed", NodeStatus.QUOTA_EXHAUSTED, article=article_id)
        budget.abort(run_id, str(exc))
        raise
    except Fatal as exc:
        circuit.record_failure(exc)
        raise
    except Transient as exc:
        circuit.record_failure(exc)
        raise
    memory.store_embedding(article, vectors[0], model)
    return {"article": article_id, "status": "stored", "dimensions": len(vectors[0])}


@shared_task(name="inference.embed_missing")
def embed_missing(limit: int = 200, run_id: str = "embeddings") -> dict:
    """Queue embeddings for canonical articles that do not have one yet."""
    if not circuit.preflight():
        log_action("inference.embed_missing", "circuit_open", reason=circuit.block_reason())
        return {"queued": 0, "status": "circuit_open", "reason": circuit.block_reason()}
    ids = list(
        Article.objects.canonical()
        .exclude(url_status=UrlStatus.GONE)
        .exclude(embeddings__model=settings.GAPGPT_EMBEDDING_MODEL)
        .values_list("id", flat=True)[:limit]
    )
    for article_id in ids:
        embed_article.delay(article_id, run_id)
    return {"queued": len(ids)}


def _outstanding_for(variant: PromptVariant, limit: int, window_days: int) -> list[int]:
    """Select unfinished work before applying the batch limit, using current answers."""
    quarantined = DeadLetter.objects.filter(resolved_at__isnull=True).values_list(
        "article_id", flat=True
    )
    other_classified = (
        Classification.objects.filter(
            pk__in=Classification.objects.for_variant(variant).latest_ids()
        )
        .filter(category="other")
        .values_list("article_id", flat=True)
    )
    summarised = Summary.objects.for_variant(variant).values_list("article_id", flat=True)

    qs = (
        Article.objects.eligible_for_inference()
        .exclude(pk__in=quarantined)
        .exclude(pk__in=other_classified)
        .exclude(pk__in=summarised)
    )
    return list(
        qs.in_window(window_days)
        .order_by("-published_at", "-id")
        .values_list("id", flat=True)[:limit]
    )


@shared_task(name="inference.run_cycle")
def run_cycle(limit: int | None = None, variant_names: list[str] | None = None) -> dict:
    """One inference pass over everything eligible and not yet answered.

    Runs every ACTIVE variant, which is what produces the paired output the A/B tab
    compares. With one active variant this is just the pipeline; with two it is the
    experiment, at twice the cost - which is why activating a variant is deliberate.
    """
    variants = PromptVariant.objects.filter(is_active=True)
    if variant_names:
        variants = PromptVariant.objects.filter(name__in=variant_names)
    variants = list(variants)
    if not variants:
        return {"error": "no active prompt variants"}
    if not circuit.preflight():
        reason = circuit.block_reason()
        log_action("inference.cycle", "circuit_open", reason=reason)
        return {
            "status": "circuit_open",
            "reason": reason,
            "articles": 0,
            "dispatched": 0,
        }

    batch_limit = limit or 200
    window_days = settings.NEWS_ROLLING_WINDOW_DAYS

    work = [
        (variant, outstanding)
        for variant in variants
        if (outstanding := _outstanding_for(variant, limit=batch_limit, window_days=window_days))
    ]
    if not work:
        # No Run row either. A run that dispatched nothing is not a run, and one per
        # 30 minutes forever is noise in the only table an operator reads for cost.
        return {
            "articles": 0,
            "variants": [variant.name for variant in variants],
            "dispatched": 0,
        }

    all_article_ids = set()
    for _, outstanding in work:
        all_article_ids.update(outstanding)

    run = Run.objects.create(mode="pipeline")
    budget.reset(run.run_id)

    dispatched = 0
    for variant, outstanding in work:
        for article_id in outstanding:
            process_article.delay(article_id, variant.pk, run.run_id)
            dispatched += 1

    Run.objects.filter(pk=run.pk).update(articles_fetched=len(all_article_ids))
    return {
        "run_id": run.run_id,
        "articles": len(all_article_ids),
        "variants": [variant.name for variant in variants],
        "dispatched": dispatched,
    }


@shared_task(name="inference.finalize_run")
def finalize_run(run_id: str) -> dict:
    """Roll per-event costs up onto the run row once its tasks have drained."""
    run = Run.objects.filter(run_id=run_id).first()
    if run is None:
        return {"error": f"no run {run_id}"}
    totals = run.events.aggregate(
        cost=Sum("cost_usd"), tin=Sum("tokens_in"), tout=Sum("tokens_out")
    )
    processed = run.events.filter(status=NodeStatus.SUCCESS).values("article").distinct().count()
    if run.status == RunStatus.RUNNING:
        run.status = _status_from_events(run)
    run.finished_at = timezone.now()
    run.cost_usd = totals["cost"] or 0
    run.tokens_in = totals["tin"] or 0
    run.tokens_out = totals["tout"] or 0
    run.articles_processed = processed
    run.save()
    return {"run_id": run_id, "cost_usd": float(run.cost_usd), "processed": processed}


@shared_task(name="inference.finalize_stale_runs")
def finalize_stale_runs(idle_minutes: int = 10) -> dict:
    """Close every run whose tasks have stopped writing events.

    A periodic sweep rather than a Celery chord callback on `run_cycle`. A chord fires only
    when EVERY task in its group completes, so one worker killed mid-article leaves the run
    `running` with a $0 cost for the life of the deployment - which is the exact state this
    exists to clear. "Nothing has written an event for ten minutes" is also true when the
    worker died, and that is the point: this closes the books either way.

    Idempotent: `finalize_run` moves the run out of RUNNING, so a run is only ever swept
    once, and an ABORTED or FAILED run keeps the status that explains what happened.
    """
    cutoff = timezone.now() - timedelta(minutes=idle_minutes)
    closed = []
    for run in Run.objects.filter(status=RunStatus.RUNNING, started_at__lte=cutoff):
        last_event = run.events.aggregate(last=Max("created_at"))["last"]
        if last_event and last_event > cutoff:
            continue  # still working
        finalize_run(run.run_id)
        closed.append(run.run_id)
    return {"closed": len(closed), "run_ids": closed}


def _status_from_events(run: Run) -> str:
    """A drained run is not automatically a success. Empty-wallet cycles used to close as
    `success` because every task returned a dict instead of raising, and /ops looked fine.
    """
    statuses = list(run.events.values_list("status", flat=True))
    if not statuses:
        return RunStatus.NO_WORK
    if NodeStatus.QUOTA_EXHAUSTED in statuses:
        return RunStatus.QUOTA_EXHAUSTED
    if NodeStatus.CIRCUIT_OPEN in statuses:
        return RunStatus.CIRCUIT_OPEN
    if NodeStatus.FATAL in statuses:
        return RunStatus.ABORTED
    successes = statuses.count(NodeStatus.SUCCESS)
    failures = [
        status
        for status in statuses
        if status not in {NodeStatus.SUCCESS, NodeStatus.SKIPPED, NodeStatus.RETRY}
    ]
    if successes and failures:
        return RunStatus.PARTIAL
    if successes or set(statuses) <= {NodeStatus.SKIPPED}:
        return RunStatus.SUCCESS if successes else RunStatus.NO_WORK
    return RunStatus.FAILED


@shared_task(name="inference.probe_circuit")
def probe_circuit() -> dict:
    """Weekly wallet check. The only inference-side call allowed while the circuit is open."""
    result = circuit.weekly_probe()
    status = result.get("status") or result.get("action") or "ok"
    log_action(
        "inference.probe",
        status,
        **{k: v for k, v in result.items() if k not in ("action", "status")},
    )
    return result
