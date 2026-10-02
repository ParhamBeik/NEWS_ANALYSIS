"""Reader tiers: relative to the month, ties resolve down, fixed bands when data is thin."""

import pytest
from rest_framework.test import APIClient

from articles.models import NewsEvent
from core import tiers
from core.events import attach_article

pytestmark = pytest.mark.django_db


def test_quantile_cutoffs_match_target_shares_and_never_inflate_ties():
    scores = list(range(1000))
    cuts = tiers.quantile_cutoffs(scores)
    assert [sum(s >= cut for s in scores) for cut in cuts] == [600, 300, 100, 20]
    # 5% tie at the top: the top tier stays empty rather than holding 5%.
    tied = [100] * 50 + [50] * 950
    assert tiers.quantile_cutoffs(tied)[3] == float("inf")
    assert tiers.tier(100, "iran", {"iran": tiers.quantile_cutoffs(tied)}) == 4


def test_api_tiers_fall_back_to_bands_then_follow_the_distribution(make_article):
    event = attach_article(make_article())
    NewsEvent.objects.filter(pk=event.pk).update(
        category="macro_monetary", iran_score=75, global_score=25
    )
    first = APIClient().get(f"/api/public/events/{event.pk}/").data
    assert (first["iran_tier"], first["global_tier"], first["impact_tier"]) == (4, 2, 3)

    # 300 more events spread over 0-100: a quarter of the month scores 75 or more for
    # Iran, so 75 is a tier-3 score now, not the fixed band's tier 4.
    for n in range(300):
        other = attach_article(make_article())
        NewsEvent.objects.filter(pk=other.pk).update(
            category="macro_monetary", iran_score=n % 101, global_score=0
        )
    tiers.cache.delete(tiers.CACHE_KEY)
    later = APIClient().get(f"/api/public/events/{event.pk}/").data
    assert later["iran_tier"] == 3
    assert tiers.cutoffs()["basis"] == "relative"
