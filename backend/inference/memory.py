"""Retrieval: what past context, if any, the model sees alongside an article.

This module IS the A/B experiment. `MemoryStrategy.NONE` is the control arm and must stay
genuinely empty - not "semantic with k=0" - so that "does memory help?" has a clean answer.

Three properties this enforces, each of which would otherwise quietly invalidate the
comparison:

1. ONLY PAST ARTICLES. A neighbour published after the article being scored is future
   information. On a news corpus that leak is severe and flattering: the follow-up
   coverage of an event is the single most similar document to the event itself, and it
   already knows how the story turned out.

2. HUMAN LABELS ARE MARKED AS SUCH. Approved review labels come first; model verdicts are
   used to top up only when there are not enough, and arrive tagged
   `human_reviewed: false`. Feeding the model its own earlier guesses as though they were
   ground truth is self-reinforcement - the corpus converges on whatever it decided first,
   and agreement metrics rise while accuracy does not.

3. THE ARTICLE ITSELF IS EXCLUDED. Obvious, and exactly the kind of thing that silently
   turns a retrieval experiment into a copy of the answer.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.db.models import Q
from pgvector.django import CosineDistance

from core.text import jaccard, trigrams
from core.vocabulary import AXES

from .models import MemoryStrategy
from .prompts import MemoryExample

logger = logging.getLogger(__name__)

# How many candidate rows to consider before ranking. Bounded so a growing corpus does not
# turn every inference into a full-table scan.
CANDIDATE_LIMIT = 400


def embedding_text(article) -> str:
    """What gets embedded: headline plus lead.

    Not the body. The body is dominated by boilerplate - agency sign-offs, related-link
    blocks, provincial datelines - and embedding it makes two unrelated articles from the
    same desk look similar. Title and lead are what an editor would skim to decide whether
    two stories are the same story.
    """
    return f"{article.original_title}\n{article.lead}".strip()[:2000]


def store_embedding(article, vector: list[float], model: str) -> None:
    from articles.models import ArticleEmbedding

    ArticleEmbedding.objects.update_or_create(
        article=article,
        model=model,
        defaults={"vector": vector, "dimensions": len(vector)},
    )


# ------------------------------------------------------------------------- formatting


def _output_for(task: str, *, category, scores: dict, one_line: str) -> str:
    """The verdict a neighbour carries, shaped to the task being asked."""
    if task == "classification":
        payload = {"category": category}
    elif task == "evaluation":
        payload = scores
    else:
        payload = {"one_line": one_line}
    return json.dumps(payload, ensure_ascii=False)


def _from_review(review, task: str) -> MemoryExample:
    return MemoryExample(
        title=review.article.original_title,
        category=review.reviewed_category,
        output=_output_for(
            task,
            category=review.reviewed_category,
            scores={
                **{axis: getattr(review, axis) for axis in AXES},
                "gold_trend": review.gold_trend,
            },
            one_line=review.one_line,
        ),
        reviewed=True,
    )


def _from_model(article, task: str) -> MemoryExample | None:
    """A neighbour labelled only by the model. Marked unreviewed so the prompt can say so."""
    classification = article.classifications.first()
    if classification is None:
        return None
    evaluation = article.evaluations.first()
    summary = article.summaries.first()
    scores = (
        {
            **{axis: getattr(evaluation, axis) for axis in AXES},
            "gold_trend": evaluation.gold_trend,
        }
        if evaluation
        else {}
    )
    if task == "evaluation" and not scores:
        return None
    if task == "summary" and summary is None:
        return None
    return MemoryExample(
        title=article.original_title,
        category=classification.category,
        output=_output_for(
            task,
            category=classification.category,
            scores=scores,
            one_line=summary.one_line if summary else "",
        ),
        reviewed=False,
    )


# -------------------------------------------------------------------------- retrieval


def _reviewed_candidates(article, category: str | None):
    from review.models import ReviewCase, ReviewStatus

    rows = (
        ReviewCase.objects.filter(status=ReviewStatus.APPROVED)
        .exclude(reviewed_category="")
        .exclude(article_id=article.pk)
        .select_related("article")
    )
    if article.published_at is not None:
        rows = rows.filter(
            Q(article__published_at__lt=article.published_at)
            | Q(article__published_at__isnull=True)
        )
    if category:
        rows = rows.filter(reviewed_category__in=[category, "security/economics"])
    return rows[:CANDIDATE_LIMIT]


def _trigram_ranked(article, category: str | None, task: str, k: int) -> list[MemoryExample]:
    """The pre-embedding baseline: nearest approved labels by title trigram similarity."""
    terms = trigrams(article.original_title)
    scored = [
        (jaccard(terms, trigrams(review.article.original_title)), review)
        for review in _reviewed_candidates(article, category)
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [_from_review(review, task) for _, review in scored[:k]]


def _semantic_ranked(article, category: str | None, task: str, k: int) -> list[MemoryExample]:
    """Nearest neighbours by embedding cosine distance, human labels first."""
    from articles.models import Article, ArticleEmbedding

    own = ArticleEmbedding.objects.filter(
        article=article, model=settings.GAPGPT_EMBEDDING_MODEL
    ).first()
    if own is None:
        # No vector yet: fall back rather than silently returning an empty control arm,
        # which would make a semantic variant look identical to `none` in the A/B results.
        logger.debug("no embedding for article %s; falling back to trigram", article.pk)
        return _trigram_ranked(article, category, task, k)

    reviewed = list(_reviewed_candidates(article, category))
    by_article = {review.article_id: review for review in reviewed}
    examples: list[MemoryExample] = []

    if by_article:
        nearest = (
            ArticleEmbedding.objects.filter(
                article_id__in=by_article, model=own.model
            )
            .annotate(distance=CosineDistance("vector", own.vector))
            .order_by("distance")[:k]
        )
        examples = [_from_review(by_article[row.article_id], task) for row in nearest]

    if len(examples) >= k:
        return examples

    # Top up with model-labelled neighbours, tagged unreviewed. With a handful of human
    # labels this is what stops the semantic arm from being an empty control by accident.
    used = set(by_article) | {article.pk}
    candidates = (
        Article.objects.canonical()
        .exclude(pk__in=used)
        .filter(embeddings__model=own.model)
    )
    if article.published_at is not None:
        candidates = candidates.filter(published_at__lt=article.published_at)
    nearest = (
        candidates.annotate(distance=CosineDistance("embeddings__vector", own.vector))
        .order_by("distance")
        .prefetch_related("classifications", "evaluations", "summaries")[: k * 3]
    )
    for neighbour in nearest:
        if len(examples) >= k:
            break
        if (example := _from_model(neighbour, task)) is not None:
            examples.append(example)
    return examples


def retrieve(article, variant, task: str, category: str | None = None) -> list[MemoryExample]:
    """The context for one inference call, per the variant's configured strategy."""
    strategy = variant.memory_strategy
    if strategy == MemoryStrategy.NONE:
        return []
    k = max(variant.memory_k, 0)
    if k == 0:
        return []
    if strategy == MemoryStrategy.TRIGRAM:
        return _trigram_ranked(article, category, task, k)
    return _semantic_ranked(article, category, task, k)


def market_context(article) -> dict | None:
    """Recent gold and dollar movement, for the `semantic+market` arm.

    Deliberately coarse: the last observed price and the change over the preceding week.
    Handing the model a full series would invite it to do arithmetic it is bad at, when
    the question being asked is only "is this a calm week or a moving one?".
    """
    from market.models import PriceSnapshot, Symbol

    moment = article.published_at
    if moment is None:
        return None
    context: dict[str, dict] = {}
    for symbol in (Symbol.GOLD_18K, Symbol.USD_IRR):
        latest = PriceSnapshot.last_before(symbol, moment)
        if latest is None:
            continue
        from datetime import timedelta

        earlier = PriceSnapshot.last_before(symbol, moment - timedelta(days=7))
        entry: dict = {"price": float(latest.price), "as_of": latest.observed_at.isoformat()}
        if earlier is not None and earlier.price:
            change = (float(latest.price) - float(earlier.price)) / float(earlier.price)
            entry["change_7d_pct"] = round(change * 100, 2)
        context[symbol] = entry
    return context or None
