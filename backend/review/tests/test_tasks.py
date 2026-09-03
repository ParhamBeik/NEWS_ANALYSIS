"""The samplers that fill the two human-judgement queues.

Both queues had a model, an API and a screen, and nothing that ever wrote a row - so
`/review` and `/ab` rendered their empty states on a healthy deployment and every agreement
metric on `/kpi` stayed null. These tests are about the producers existing and about the
two properties that make their output usable: the stratum is recorded, and a pair is only
built where there is actually something to compare.
"""

from __future__ import annotations

import pytest

from core.vocabulary import Category
from inference.models import Classification, Evaluation, MemoryStrategy, PromptVariant
from review.models import ABPair, ReviewCase
from review.tasks import build_ab_pairs, sample_review_cases

pytestmark = pytest.mark.django_db


def classify(article, variant, category=Category.SECURITY):
    return Classification.objects.create(
        article=article, variant=variant, prompt_version=variant.prompt_version,
        provider=variant.provider, model=variant.model, category=category,
    )


def evaluate(article, variant):
    return Evaluation.objects.create(
        article=article, variant=variant, prompt_version=variant.prompt_version,
        provider=variant.provider, model=variant.model,
        confidence_occurrence="زیاد", security_relevance="زیاد",
    )


@pytest.fixture
def challenger(variant) -> PromptVariant:
    return PromptVariant.objects.create(
        name="semantic-memory", model=variant.model,
        memory_strategy=MemoryStrategy.SEMANTIC, is_active=True,
    )


class TestReviewSampler:
    def test_it_queues_articles_at_all(self, make_article, variant):
        """Nothing created a ReviewCase outside the legacy importer and the tests, so the
        labelling queue was permanently empty and /kpi had nothing to compute against."""
        for _ in range(3):
            classify(make_article(), variant)
        assert sample_review_cases(limit=10)["queued"] == 3
        assert ReviewCase.objects.count() == 3

    def test_the_stratum_is_recorded_not_inferred_later(self, make_article, variant):
        """/kpi reports agreement PER STRATUM. Without the reason stored at sampling time
        the rate is one number over a sample nobody can characterise afterwards."""
        article = make_article()
        classify(article, variant, category=Category.OTHER)
        sample_review_cases(limit=10)
        assert ReviewCase.objects.get(article=article).stratum

    def test_a_disagreement_is_preferred_over_a_round_robin_pick(
        self, make_article, variant, challenger
    ):
        """The cases worth a human's time are the ones the model is demonstrably unsure
        about; a queue of easy articles measures how often the news was obvious."""
        contested = make_article()
        classify(contested, variant, category=Category.SECURITY)
        classify(contested, challenger, category=Category.ECONOMICS)

        sample_review_cases(limit=10)
        assert ReviewCase.objects.get(article=contested).stratum == "disagreement"

    def test_an_article_is_never_queued_twice(self, make_article, variant):
        """`ReviewCase.article` is a OneToOne, so a second pass over the same article is an
        integrity error rather than a duplicate to clean up later."""
        classify(make_article(), variant)
        sample_review_cases(limit=10)
        assert sample_review_cases(limit=10)["queued"] == 0
        assert ReviewCase.objects.count() == 1


class TestABPairBuilder:
    def test_a_single_active_variant_produces_no_pairs(self, make_article, variant):
        """One active arm is the normal, cheap configuration - not an error state."""
        article = make_article()
        evaluate(article, variant)
        assert build_ab_pairs()["created"] == 0

    def test_two_arms_on_the_same_article_produce_a_pair(
        self, make_article, variant, challenger
    ):
        article = make_article()
        evaluate(article, variant)
        evaluate(article, challenger)

        assert build_ab_pairs()["created"] == 1
        pair = ABPair.objects.get()
        assert pair.article_id == article.pk
        assert {pair.variant_a_id, pair.variant_b_id} == {variant.pk, challenger.pk}

    def test_an_article_only_one_arm_evaluated_is_not_paired(
        self, make_article, variant, challenger
    ):
        """A card with no scores on one side is not a head-to-head - it is a blank the
        reviewer has to guess at, and the judgement it collects is noise in the standings.
        """
        article = make_article()
        evaluate(article, variant)
        assert build_ab_pairs()["created"] == 0
        assert ABPair.objects.count() == 0

    def test_running_twice_does_not_duplicate_a_head_to_head(
        self, make_article, variant, challenger
    ):
        article = make_article()
        evaluate(article, variant)
        evaluate(article, challenger)
        build_ab_pairs()
        assert build_ab_pairs()["created"] == 0
        assert ABPair.objects.count() == 1
