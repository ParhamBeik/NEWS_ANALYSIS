"""Retrieval - the A/B experiment's independent variable.

Most of these tests defend the VALIDITY of the comparison rather than the quality of the
retrieval. A leak here does not crash anything; it just makes the memory arm look better
than it is, which is worse.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from articles.models import ArticleEmbedding
from inference import memory
from inference.models import Classification, MemoryStrategy, PromptVariant
from review.models import ReviewCase, ReviewStatus

pytestmark = pytest.mark.django_db

DIM = 1536


def vector(seed: float) -> list[float]:
    return [seed] + [0.0] * (DIM - 1)


@pytest.fixture
def control(db) -> PromptVariant:
    return PromptVariant.objects.create(
        name="control", model="m", memory_strategy=MemoryStrategy.NONE
    )


@pytest.fixture
def semantic(db) -> PromptVariant:
    return PromptVariant.objects.create(
        name="semantic", model="m", memory_strategy=MemoryStrategy.SEMANTIC, memory_k=3
    )


@pytest.fixture
def trigram(db) -> PromptVariant:
    return PromptVariant.objects.create(
        name="trigram", model="m", memory_strategy=MemoryStrategy.TRIGRAM, memory_k=3
    )


def approve(article, category="security", **scores):
    return ReviewCase.objects.create(
        article=article,
        stratum="test",
        status=ReviewStatus.APPROVED,
        reviewed_category=category,
        confidence_occurrence=scores.get("confidence_occurrence", "زیاد"),
        security_relevance=scores.get("security_relevance", "زیاد"),
        one_line="خلاصه تاییدشده",
    )


class TestControlArm:
    def test_none_returns_nothing_at_all(self, article, make_article, control):
        approve(make_article(original_title="خبر مشابه"))
        assert memory.retrieve(article, control, "classification") == []

    def test_zero_k_returns_nothing(self, article, make_article, semantic):
        approve(make_article())
        semantic.memory_k = 0
        assert memory.retrieve(article, semantic, "classification") == []


class TestNoFutureLeak:
    def test_articles_published_later_are_excluded(self, make_article, trigram):
        """The severe one. On a news corpus, the single most similar document to an event
        is the follow-up coverage of that event - which already knows how it turned out."""
        now = timezone.now()
        subject = make_article(original_title="حمله به تاسیسات نفتی", published_at=now)
        future = make_article(
            original_title="حمله به تاسیسات نفتی", published_at=now + timedelta(hours=6)
        )
        approve(future)
        assert memory.retrieve(subject, trigram, "classification") == []

    def test_earlier_articles_are_retrieved(self, make_article, trigram):
        now = timezone.now()
        past = make_article(
            original_title="حمله به تاسیسات نفتی", published_at=now - timedelta(hours=6)
        )
        approve(past)
        subject = make_article(original_title="حمله به تاسیسات نفتی", published_at=now)
        assert len(memory.retrieve(subject, trigram, "classification")) == 1

    def test_the_article_itself_is_never_returned(self, article, trigram):
        approve(article)
        assert memory.retrieve(article, trigram, "classification") == []


class TestProvenance:
    def test_human_labels_are_marked_reviewed(self, make_article, trigram):
        now = timezone.now()
        approve(make_article(original_title="عنوان مشابه", published_at=now - timedelta(hours=1)))
        subject = make_article(original_title="عنوان مشابه", published_at=now)
        examples = memory.retrieve(subject, trigram, "classification")
        assert examples and all(example.reviewed for example in examples)

    def test_model_verdicts_are_marked_unreviewed(self, make_article, semantic, variant):
        """Self-reinforcement guard. If the model's own earlier guesses arrived looking
        like ground truth, the corpus converges on whatever it decided first and agreement
        metrics rise while accuracy does not."""
        now = timezone.now()
        neighbour = make_article(original_title="خبر قبلی", published_at=now - timedelta(hours=2))
        Classification.objects.create(
            article=neighbour, variant=variant, prompt_version=variant.prompt_version,
            provider="gapgpt", model="m", category="security",
        )
        ArticleEmbedding.objects.create(
            article=neighbour, model="text-embedding-3-small", dimensions=DIM, vector=vector(1.0)
        )
        subject = make_article(published_at=now)
        ArticleEmbedding.objects.create(
            article=subject, model="text-embedding-3-small", dimensions=DIM, vector=vector(1.0)
        )
        examples = memory.retrieve(subject, semantic, "classification")
        assert examples and not any(example.reviewed for example in examples)


class TestTaskShaping:
    def test_classification_examples_carry_only_the_category(self, make_article, trigram):
        now = timezone.now()
        approve(make_article(original_title="عنوان", published_at=now - timedelta(hours=1)))
        subject = make_article(original_title="عنوان", published_at=now)
        output = memory.retrieve(subject, trigram, "classification")[0].output
        assert "category" in output and "confidence_occurrence" not in output

    def test_evaluation_examples_carry_the_axes(self, make_article, trigram):
        now = timezone.now()
        approve(make_article(original_title="عنوان", published_at=now - timedelta(hours=1)))
        subject = make_article(original_title="عنوان", published_at=now)
        output = memory.retrieve(subject, trigram, "evaluation")[0].output
        assert "confidence_occurrence" in output and "gold_trend" in output

    def test_summary_examples_carry_only_the_one_line(self, make_article, trigram):
        now = timezone.now()
        approve(make_article(original_title="عنوان", published_at=now - timedelta(hours=1)))
        subject = make_article(original_title="عنوان", published_at=now)
        output = memory.retrieve(subject, trigram, "summary")[0].output
        assert "one_line" in output and "category" not in output


class TestSemanticFallback:
    def test_missing_embedding_falls_back_to_trigram(self, make_article, semantic):
        """Returning nothing would silently turn the semantic arm into a second control
        arm, and the A/B result would report 'memory makes no difference'."""
        now = timezone.now()
        approve(make_article(original_title="حمله موشکی", published_at=now - timedelta(hours=1)))
        subject = make_article(original_title="حمله موشکی", published_at=now)
        assert len(memory.retrieve(subject, semantic, "classification")) == 1


class TestEmbeddingText:
    def test_embeds_title_and_lead_not_the_body(self, make_article):
        """Bodies are dominated by boilerplate - agency sign-offs, related-link blocks,
        provincial datelines - which makes two unrelated articles from the same desk look
        similar."""
        article = make_article(
            original_title="تیتر", lead="خلاصه", content="متن بسیار طولانی " * 500
        )
        text = memory.embedding_text(article)
        assert "تیتر" in text and "خلاصه" in text
        assert len(text) <= 2000


class TestMarketContext:
    def test_returns_none_without_prices(self, article):
        assert memory.market_context(article) is None

    def test_returns_none_for_an_undated_article(self, make_article):
        assert memory.market_context(make_article(published_at=None)) is None

    def test_reports_price_and_weekly_change(self, make_article):
        from market.models import PriceSnapshot, Symbol

        now = timezone.now()
        PriceSnapshot.objects.create(
            symbol=Symbol.GOLD_18K, price=100, observed_at=now - timedelta(days=8)
        )
        PriceSnapshot.objects.create(
            symbol=Symbol.GOLD_18K, price=110, observed_at=now - timedelta(hours=1)
        )
        context = memory.market_context(make_article(published_at=now))
        assert context[Symbol.GOLD_18K]["change_7d_pct"] == pytest.approx(10.0)


class TestEvaluationNeighbourFiltering:
    def test_category_filter_keeps_cross_cutting_examples(self, make_article, trigram):
        """A `security/economics` precedent is relevant when scoring either a security or
        an economics article - it is the only category that spans both."""
        now = timezone.now()
        approve(
            make_article(original_title="خبر امنیتی اقتصادی", published_at=now - timedelta(hours=1)),
            category="security/economics",
        )
        subject = make_article(original_title="خبر امنیتی اقتصادی", published_at=now)
        assert memory.retrieve(subject, trigram, "evaluation", category="economics")

    def test_unrelated_category_is_filtered_out(self, make_article, trigram):
        now = timezone.now()
        approve(
            make_article(original_title="عنوان مشترک", published_at=now - timedelta(hours=1)),
            category="security",
        )
        subject = make_article(original_title="عنوان مشترک", published_at=now)
        assert memory.retrieve(subject, trigram, "evaluation", category="economics") == []
