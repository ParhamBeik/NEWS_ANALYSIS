"""The cost prefilter - the one optimisation that can silently lose a real story.

Every test here is about that risk, not about the saving. The saving is easy; not
suppressing a border incident filed under a provincial desk is the hard part.
"""

from __future__ import annotations

import pytest

from articles.models import Article
from sources import prefilter
from sources.models import PrefilterRule, Source, Strategy

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_rule_cache():
    prefilter.reload_rules()
    yield
    prefilter.reload_rules()


@pytest.fixture
def isna(db) -> Source:
    return Source.objects.create(
        name="isna", strategy=Strategy.RSS_SABA, url="https://www.isna.ir/rss", priority=4
    )


class TestRuleCache:
    """The rules are cached; the question is for how long, and who finds out.

    An `lru_cache` here was effectively permanent. Every gunicorn worker, every Celery
    child and beat hold their own copy, and `reload_rules()` only ever reaches the process
    that calls it - so enabling a rule in the admin kept costing money in the four
    processes that were not listening, and disabling one kept holding real articles back,
    until the next redeploy.
    """

    def test_a_rule_added_elsewhere_is_picked_up_when_the_cache_expires(self, source):
        assert prefilter.reason_for(source.name, "sports") == ""  # warms the cache
        PrefilterRule.objects.create(source=source, native_category="sports", enabled=True)
        # Still stale inside the TTL, which is the deliberate trade.
        assert prefilter.reason_for(source.name, "sports") == ""

        prefilter._cache["expires_at"] = 0.0  # as if CACHE_TTL_SECONDS had elapsed
        assert prefilter.reason_for(source.name, "sports") == "native_category:sports"

    def test_the_ttl_is_short_enough_to_be_an_operational_answer(self):
        """A rule change has to take effect without a redeploy. Minutes is not that."""
        assert 0 < prefilter.CACHE_TTL_SECONDS <= 300


class TestScoping:
    def test_no_rules_means_nothing_is_suppressed(self, source):
        assert prefilter.reason_for(source.name, "sports") == ""

    def test_a_rule_suppresses_only_its_own_source(self, source, isna):
        """The slug vocabularies are not shared. Mehr emits CamelCase desk names, IRNA
        lowercase names plus abbreviations, ISNA bare numeric ids - so '6004' means one
        thing at ISNA and nothing at all at Mehr. A global list would suppress the wrong
        desk at two of the three."""
        PrefilterRule.objects.create(source=isna, native_category="6004", enabled=True)
        prefilter.reload_rules()
        assert prefilter.reason_for(isna.name, "6004") == "native_category:6004"
        assert prefilter.reason_for(source.name, "6004") == ""

    def test_a_global_rule_applies_everywhere(self, source, isna):
        PrefilterRule.objects.create(source=None, native_category="soccer", enabled=True)
        prefilter.reload_rules()
        assert prefilter.reason_for(source.name, "soccer")
        assert prefilter.reason_for(isna.name, "soccer")

    def test_a_disabled_rule_suppresses_nothing(self, isna):
        PrefilterRule.objects.create(source=isna, native_category="6004", enabled=False)
        prefilter.reload_rules()
        assert prefilter.reason_for(isna.name, "6004") == ""

    def test_matching_is_case_insensitive(self, source):
        PrefilterRule.objects.create(source=source, native_category="parliament", enabled=True)
        prefilter.reload_rules()
        assert prefilter.reason_for(source.name, "Parliament")

    def test_an_article_with_no_slug_is_always_eligible(self, source):
        """Khabarfoori and Shahrekhabar publish no taxonomy. There is no default-deny."""
        PrefilterRule.objects.create(source=source, native_category="x", enabled=True)
        prefilter.reload_rules()
        assert prefilter.reason_for(source.name, "") == ""


class TestReapply:
    def test_disabling_a_rule_releases_the_articles_it_held(self, source, make_article):
        """A switch that does not release what it held is a lie, and the corpus stays
        quietly truncated."""
        rule = PrefilterRule.objects.create(
            source=source, native_category="sports", enabled=True
        )
        make_article(native_category="sports", prefilter_reason="native_category:sports")

        rule.enabled = False
        rule.save()
        result = prefilter.reapply()

        assert result["released"] == 1
        assert Article.objects.filter(prefilter_reason="").count() == 1

    def test_enabling_a_rule_holds_back_matching_articles(self, source, make_article):
        make_article(native_category="sports")
        PrefilterRule.objects.create(source=source, native_category="sports", enabled=True)
        result = prefilter.reapply()

        assert result["held"] == 1
        assert Article.objects.get(native_category="sports").prefilter_reason == (
            "native_category:sports"
        )

    def test_reapply_is_idempotent(self, source, make_article):
        PrefilterRule.objects.create(source=source, native_category="sports", enabled=True)
        make_article(native_category="sports")
        prefilter.reapply()
        assert prefilter.reapply() == {"held": 0, "released": 0}


class TestEligibility:
    def test_prefiltered_articles_are_stored_but_not_inferred(self, source, make_article):
        """Storage and spending are separate decisions. The article stays in full so the
        suppression is auditable and reversible."""
        held = make_article(
            native_category="sports", prefilter_reason="native_category:sports"
        )
        eligible = make_article()
        assert Article.objects.filter(pk=held.pk).exists()
        ids = set(Article.objects.eligible_for_inference().values_list("id", flat=True))
        assert ids == {eligible.pk}


class TestObservedSlugs:
    def test_reports_volume_per_slug_for_tuning(self, source, make_article):
        """You switch a rule on against evidence that the desk produces only `other`, not
        because the slug sounds unimportant."""
        for _ in range(6):
            make_article(native_category="parliament")
        rows = prefilter.observed_slugs(min_articles=5)
        assert rows and rows[0]["native_category"] == "parliament"
        assert rows[0]["articles"] == 6
        assert rows[0]["other_share"] is None, "no classifications yet means no evidence yet"

    def test_low_volume_slugs_are_excluded(self, source, make_article):
        make_article(native_category="rare")
        assert prefilter.observed_slugs(min_articles=5) == []
