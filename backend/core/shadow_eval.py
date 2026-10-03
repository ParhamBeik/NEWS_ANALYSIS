"""Shadow eval: the release gate for a decision prompt or model change.

Re-asks the current decision backend (inference.jev.decide, so the run/day/month budget
and the provider circuit apply) about items staff already labelled, and compares:

- swipe reviews (EventReview): topic, and the Iran and global impact tiers (exact and
  within one level, on core.review's fixed bands);
- grouping decisions (GroupingDecision): whether the article is the same occurrence as
  the event, judged by the production merge rule (jev.matched_event).

Nothing the backend answers is written to the event: no EventAssessment, no score change.
One compact EvalRun row keeps the aggregate metrics (docs/STORAGE-POLICY.md: no per-item
copies). Results are per backend and model, because GapGPT fallback confidences are
self-reported, not calibrated, and are never comparable with TypeSafe's.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.db.models import F

from articles.models import EventReview, GroupingDecision
from core.errors import BudgetExceeded, Fatal, Permanent, Transient
from core.review import score_tier
from core.vocabulary import EVENT_CATEGORIES, event_topic
from inference import budget, circuit, jev
from inference.models import EvalRun

LANGUAGES = ("fa", "en", "all")
# Persian packs fewer characters per token than English; 3 overstates both on purpose.
CHARS_PER_TOKEN = 3


class EvalUnavailable(Exception):
    """No backend configured, or the provider circuit is open: nothing was asked."""


@dataclass(frozen=True)
class Item:
    language: str
    topic: str
    iran: int
    global_: int
    predicted_topic: str | None = None
    predicted_iran: int | None = None
    predicted_global: int | None = None


def labelled_reviews(language: str = "all", limit: int | None = None):
    rows = (
        EventReview.objects.filter(
            status=EventReview.Status.REVIEWED,
            reviewed_category__gt="",
            reviewed_iran_score__isnull=False,
            reviewed_global_score__isnull=False,
        )
        .select_related("event__primary_article__source")
        .order_by("-reviewed_at", "-id")
    )
    if language != "all":
        rows = rows.filter(event__primary_article__source__language=language)
    return list(rows[:limit] if limit else rows)


def labelled_groupings(language: str = "all", limit: int | None = None):
    # An event's own primary article is not a grouping question.
    rows = (
        GroupingDecision.objects.exclude(article_id=F("event__primary_article_id"))
        .select_related("article__source", "event__primary_article")
        .order_by("-decided_at", "-id")
    )
    if language != "all":
        rows = rows.filter(article__source__language=language)
    return list(rows[:limit] if limit else rows)


def _candidates(decision) -> dict[str, str]:
    return jev.same_event_candidates([decision.event])


def estimate(reviews, groupings, backend: str | None = None) -> dict:
    """Upper-bound cost of asking every item once, at the configured prices.

    GapGPT pre-reserves max_tokens per request, so output is charged at that bound;
    TypeSafe output is free on its price list.
    """
    backend = backend or jev.backend_name()
    multi = backend == "gapgpt"
    payloads = [(jev.article_state(r.event.primary_article), None) for r in reviews] + [
        (jev.article_state(g.article), _candidates(g)) for g in groupings
    ]
    tokens_in = sum(
        math.ceil(
            len(
                json.dumps(
                    {"report": state, "questions": jev._questions(candidates, multi=multi)},
                    ensure_ascii=False,
                )
            )
            / CHARS_PER_TOKEN
        )
        for state, candidates in payloads
    )
    if backend == "typesafe":
        tokens_out, price_in, price_out = 0, settings.TYPESAFE_INPUT_USD_PER_MILLION, 0.0
    else:
        tokens_out = settings.NEWS_DECISION_MAX_TOKENS * len(payloads)
        price_in = settings.GAPGPT_INPUT_USD_PER_MILLION
        price_out = settings.GAPGPT_OUTPUT_USD_PER_MILLION
    return {
        "backend": backend,
        "calls": len(payloads),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round((tokens_in * price_in + tokens_out * price_out) / 1_000_000, 6),
    }


def _tier(answer) -> int | None:
    value = float(answer["score"])
    if not 0 <= value <= 4:
        raise ValueError("score outside Jev's 0-4 range")
    return score_tier(round(value * 25))


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 3) if total else None


def _within_one(label: int, predicted: int | None) -> bool:
    return predicted is not None and abs(label - predicted) <= 1


def item_metrics(items: list[Item]) -> dict:
    n = len(items)
    return {
        "items": n,
        "topic_accuracy": _rate(sum(i.predicted_topic == i.topic for i in items), n),
        "iran_tier_exact": _rate(sum(i.predicted_iran == i.iran for i in items), n),
        "iran_tier_within_one": _rate(sum(_within_one(i.iran, i.predicted_iran) for i in items), n),
        "global_tier_exact": _rate(sum(i.predicted_global == i.global_ for i in items), n),
        "global_tier_within_one": _rate(
            sum(_within_one(i.global_, i.predicted_global) for i in items), n
        ),
    }


def grouping_metrics(pairs: list[tuple[bool, bool]]) -> dict:
    """(labelled same, predicted same) pairs; "same" is the positive class."""
    tp = sum(label and predicted for label, predicted in pairs)
    fp = sum(predicted and not label for label, predicted in pairs)
    fn = sum(label and not predicted for label, predicted in pairs)
    return {
        "pairs": len(pairs),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": _rate(tp, tp + fp),
        "recall": _rate(tp, tp + fn),
    }


def metrics(items: list[Item], pairs: list[tuple[bool, bool]], cost_usd: float) -> dict:
    calls = len(items) + len(pairs)
    return {
        "overall": item_metrics(items),
        "languages": {
            lang: item_metrics([i for i in items if i.language == lang])
            for lang in sorted({i.language for i in items})
        },
        "topics": {
            topic: item_metrics([i for i in items if i.topic == topic])
            for topic in sorted({i.topic for i in items})
        },
        "grouping": grouping_metrics(pairs),
        "calls": calls,
        "cost_usd": round(cost_usd, 8),
        "mean_cost_per_item_usd": round(cost_usd / calls, 8) if calls else None,
    }


def verdict(result: dict, aborted: str = "") -> tuple[str, list[str]]:
    """Pass only when every measured threshold holds on at least NEWS_EVAL_MIN_LABELS items.

    Unanswerable items count as misses: a schema failure is no verdict at all. Grouping is
    gated only once the backend has merged something (precision is undefined before that).
    """
    if aborted:
        return EvalRun.Verdict.ABORTED, [aborted]
    overall = result["overall"]
    if overall["items"] < settings.NEWS_EVAL_MIN_LABELS:
        return EvalRun.Verdict.INSUFFICIENT_LABELS, [
            f"{overall['items']} labelled items, need {settings.NEWS_EVAL_MIN_LABELS}"
        ]
    checks = [
        ("topic accuracy", overall["topic_accuracy"], settings.NEWS_EVAL_MIN_TOPIC_ACCURACY),
        (
            "iran tier within one",
            overall["iran_tier_within_one"],
            settings.NEWS_EVAL_MIN_TIER_WITHIN_ONE,
        ),
        (
            "global tier within one",
            overall["global_tier_within_one"],
            settings.NEWS_EVAL_MIN_TIER_WITHIN_ONE,
        ),
        (
            "grouping precision",
            result["grouping"]["precision"],
            settings.NEWS_EVAL_MIN_GROUPING_PRECISION,
        ),
    ]
    reasons = [
        f"{name} {value:.3f} < {floor:.2f}"
        for name, value, floor in checks
        if value is not None and value < floor
    ]
    return (EvalRun.Verdict.FAIL if reasons else EvalRun.Verdict.PASS), reasons


class _Asker:
    """Calls jev.decide under one eval run id, applying the circuit like the tasks do."""

    def __init__(self):
        self.run_id = f"eval-{uuid.uuid4().hex[:12]}"
        self.model = ""
        self.failed = 0
        self.aborted = ""

    def __call__(self, state: dict, candidates: dict | None = None) -> dict | None:
        if reason := circuit.block_reason():
            self.aborted = f"provider circuit open: {reason}"
            return None
        try:
            response = jev.decide(state, self.run_id, candidates)
        except BudgetExceeded as exc:
            if circuit.is_wallet_failure(exc):
                circuit.open_budget(str(exc))
            self.aborted = f"budget: {exc}"
            return None
        except Fatal as exc:
            circuit.record_failure(exc)
            self.aborted = f"fatal: {exc}"
            return None
        except (Permanent, Transient) as exc:
            if isinstance(exc, Transient):
                circuit.record_failure(exc)
            self.failed += 1
            return None
        circuit.record_success()
        self.model = self.model or str(response.get("model") or "")
        return response.get("answers") or {}


def _review_item(review: EventReview, answers: dict | None) -> Item:
    article = review.event.primary_article
    item = Item(
        language=article.source.language,
        topic=event_topic(review.reviewed_category),
        iran=score_tier(review.reviewed_iran_score),
        global_=score_tier(review.reviewed_global_score),
    )
    if answers is None:
        return item
    try:
        topic = answers["category"]["choice"]
        iran, global_ = _tier(answers["iran"]), _tier(answers["global"])
    except (KeyError, TypeError, ValueError):
        return item
    return Item(
        item.language, item.topic, item.iran, item.global_,
        topic if topic in EVENT_CATEGORIES else None, iran, global_,
    )


def configured_model(backend: str) -> str:
    if backend == "typesafe":
        return settings.TYPESAFE_JEV_MODEL
    return f"gapgpt:{settings.NEWS_DECISION_FALLBACK_MODEL or settings.GAPGPT_MODEL}"


def run(*, language: str = "all", limit: int | None = None) -> EvalRun:
    """Ask the backend about every labelled item and store one EvalRun."""
    if not jev.configured():
        raise EvalUnavailable("no decision backend configured")
    if reason := circuit.block_reason():
        raise EvalUnavailable(f"provider circuit open: {reason}")
    backend = jev.backend_name()
    ask = _Asker()
    items: list[Item] = []
    for review in labelled_reviews(language, limit):
        answers = ask(jev.article_state(review.event.primary_article))
        if ask.aborted:
            break
        item = _review_item(review, answers)
        if answers is not None and item.predicted_iran is None:
            ask.failed += 1  # answered, but not in a usable shape
        items.append(item)
    pairs: list[tuple[bool, bool]] = []
    for decision in [] if ask.aborted else labelled_groupings(language, limit):
        candidates = _candidates(decision)
        answers = ask(jev.article_state(decision.article), candidates)
        if ask.aborted:
            break
        predicted = answers is not None and bool(jev.matched_event(answers, candidates))
        pairs.append((decision.decision == GroupingDecision.Decision.SAME, predicted))
    cost = budget.current(ask.run_id).run_usd
    result = metrics(items, pairs, cost)
    outcome, reasons = verdict(result, ask.aborted)
    return EvalRun.objects.create(
        backend=backend,
        model=(ask.model or configured_model(backend))[:100],
        question_hash=jev.question_hash(backend),
        language=language,
        labelled=len(items),
        grouping_pairs=len(pairs),
        failed=ask.failed,
        cost_usd=cost,
        metrics=result,
        verdict=outcome,
        reasons=reasons,
    )
