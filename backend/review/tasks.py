"""The producers for the two human-judgement queues.

`review.models` describes what a `ReviewCase` and an `ABPair` mean; nothing was creating
either, so `/review` and `/ab` rendered their empty states forever and every agreement
figure on `/kpi` stayed null on a fresh deployment. These are the samplers that fill them.

The sampler is STRATIFIED, and the stratum is stored on the row. Labelling the newest
twenty articles would measure the model on whatever the news happened to be that morning;
worse, it would over-sample the easy cases, because the articles a model is confident about
are also the ones that arrive most often. Recording which stratum a case came from is what
lets /kpi report agreement per stratum instead of as one number over a non-random sample.

Pairs are built only from articles BOTH arms actually evaluated. A pair where one side has
no scores is not a head-to-head - it is a blank card the reviewer has to guess at, and the
judgement it collects is noise in the standings.
"""

from __future__ import annotations

import itertools
import logging

from celery import shared_task
from django.db.models import Count, Q

from articles.models import Article
from core.vocabulary import CATEGORIES, Category
from inference.models import Classification, Evaluation, PromptVariant

from .models import ABPair, ReviewCase

logger = logging.getLogger(__name__)

# Per stratum, at most this share of one sampling pass. Disagreements are worth the most
# per label - they are the cases where the model is demonstrably uncertain - but a queue
# made only of disagreements would report an agreement rate for the hardest slice of the
# corpus and nothing about the rest.
STRATUM_CAP = 0.4


def _pool():
    """Canonical articles not already queued. `ReviewCase.article` is a OneToOne, so a
    second case for the same article is an integrity error, not a duplicate to dedupe."""
    return Article.objects.canonical().filter(review_case__isnull=True)


def _disagreements(pool, limit: int):
    """Articles more than one stored answer disagrees about.

    Distinct categories over ALL of an article's classifications, which catches both a
    second variant deciding differently and the same variant changing its mind after a
    prompt edit. Both are a model that is not sure, which is what makes the label valuable.
    """
    return (
        pool.annotate(distinct_categories=Count("classifications__category", distinct=True))
        .filter(distinct_categories__gt=1)
        .order_by("-published_at")
        .values_list("id", flat=True)[:limit]
    )


def _other_verdicts(pool, limit: int):
    """Articles the model dismissed as `other`.

    The cheap exit is the expensive mistake: `other` stops the chain, so a story misfiled
    here is never scored, never summarised and never shown. Nothing else in the system
    would ever catch it.
    """
    return (
        pool.filter(
            classifications__pk__in=Classification.objects.latest_ids(),
            classifications__category=Category.OTHER,
        )
        .order_by("-published_at")
        .values_list("id", flat=True)[:limit]
    )


def _unevaluated(pool, limit: int):
    """Classified as worth scoring, then never scored - a chain that died mid-way."""
    return (
        pool.filter(classifications__pk__in=Classification.objects.latest_ids())
        .exclude(classifications__category=Category.OTHER)
        .filter(evaluations__isnull=True)
        .order_by("-published_at")
        .values_list("id", flat=True)[:limit]
    )


def _round_robin(pool, limit: int) -> list[int]:
    """An even slice across categories, so the golden set is not all economics.

    Per category rather than newest-overall: the corpus is not balanced, and a sample that
    inherits its imbalance reports the model's accuracy on whatever it sees most.
    """
    per_category = max(1, limit // max(len(CATEGORIES), 1))
    picked: list[int] = []
    latest = Classification.objects.latest_ids()
    for category in CATEGORIES:
        picked.extend(
            pool.filter(
                classifications__pk__in=latest, classifications__category=category
            )
            .order_by("-published_at")
            .values_list("id", flat=True)[:per_category]
        )
    return picked


@shared_task(name="review.sample_review_cases")
def sample_review_cases(limit: int = 20) -> dict:
    """Queue up to `limit` articles for human labelling, stratified by why they matter."""
    pool = _pool()
    cap = max(1, int(limit * STRATUM_CAP))
    picked: dict[int, str] = {}

    for stratum, article_ids in (
        ("disagreement", _disagreements(pool, cap)),
        ("unevaluated", _unevaluated(pool, cap)),
        ("other", _other_verdicts(pool, cap)),
        ("round_robin", _round_robin(pool, limit)),
    ):
        for article_id in article_ids:
            if len(picked) >= limit:
                break
            picked.setdefault(article_id, stratum)

    # ignore_conflicts, not a pre-check: two sampler runs overlapping would otherwise race
    # between reading `_pool()` and inserting, and lose the whole batch to one collision.
    ReviewCase.objects.bulk_create(
        [ReviewCase(article_id=article_id, stratum=stratum)
         for article_id, stratum in picked.items()],
        ignore_conflicts=True,
    )
    by_stratum: dict[str, int] = {}
    for stratum in picked.values():
        by_stratum[stratum] = by_stratum.get(stratum, 0) + 1
    logger.info("queued %s review cases: %s", len(picked), by_stratum)
    return {"queued": len(picked), "by_stratum": by_stratum}


@shared_task(name="review.build_ab_pairs")
def build_ab_pairs(limit: int = 50) -> dict:
    """Pair every combination of active variants on the articles both of them evaluated.

    Keyed on the evaluation rather than the classification because the scores, the gold
    trend and the notify decision are what the A/B card actually asks a human to compare.
    """
    variants = list(PromptVariant.objects.filter(is_active=True).order_by("pk"))
    if len(variants) < 2:
        # Not an error. One active variant is the normal, cheap configuration; the
        # experiment is the deliberate exception.
        return {"created": 0, "reason": "fewer than two active variants"}

    created = 0
    for left, right in itertools.combinations(variants, 2):
        if created >= limit:
            break
        answered = {
            variant.pk: set(
                Evaluation.objects.for_variant(variant).values_list("article_id", flat=True)
            )
            for variant in (left, right)
        }
        # Both orderings: a pair built the other way round satisfies the unique constraint
        # but is the same head-to-head, and judging it twice double-counts one comparison.
        existing = set(
            ABPair.objects.filter(
                Q(variant_a=left, variant_b=right) | Q(variant_a=right, variant_b=left)
            ).values_list("article_id", flat=True)
        )
        outstanding = sorted(
            (answered[left.pk] & answered[right.pk]) - existing, reverse=True
        )
        for article_id in outstanding[: limit - created]:
            ABPair.objects.get_or_create(
                article_id=article_id,
                variant_a=left,
                variant_b=right,
                defaults={"shown_as_left": ABPair.random_side()},
            )
            created += 1
    logger.info("built %s a/b pairs", created)
    return {"created": created}
