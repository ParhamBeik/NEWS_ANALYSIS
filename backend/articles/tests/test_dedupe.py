"""FROZEN INVARIANT 1/4 - deduplication, tuned for precision.

The asymmetry is the whole design: a false positive silently drops a real story from the
analyst's workbook, a false negative just prints a duplicate row. Every test here defends
that asymmetry rather than raw accuracy.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from articles import dedupe
from articles.models import Article
from core.text import jaccard, trigrams
from inference.models import Classification
from sources.models import Source, Strategy

pytestmark = pytest.mark.django_db


class TestThreshold:
    def test_threshold_is_the_measured_value(self):
        """0.75, not 0.70. Sweeping every title pair in the corpus: J>=0.70 gives 44 pairs
        with one false positive at 0.704 (two cities sharing the بندر stem). 0.75 buys
        precision with recall, knowingly giving up ~5 of 44 real duplicates."""
        assert dedupe.THRESHOLD == 0.75
        assert dedupe.WINDOW_HOURS == 36

    def test_linking_agrees_with_the_threshold(self, make_article):
        """Property, not anecdote: whatever the pair, the link decision must match the
        score against THRESHOLD - no rounding, no 'close enough'."""
        first = make_article(original_title="حمله موشکی به تاسیسات نفتی در بندر عباس")
        second = make_article(original_title="حمله موشکی به تاسیسات نفتی در بندر ماهشهر")
        score = jaccard(trigrams(first.original_title), trigrams(second.original_title))
        match = dedupe.find_duplicate(second)
        assert (match is not None) == (score >= dedupe.THRESHOLD), (
            f"score {score:.3f} vs threshold {dedupe.THRESHOLD}"
        )

    def test_clearly_different_stories_are_not_merged(self, make_article):
        make_article(original_title="قیمت طلا امروز افزایش یافت")
        other = make_article(original_title="تیم ملی فوتبال به جام جهانی صعود کرد")
        assert dedupe.find_duplicate(other) is None


class TestExactMatch:
    def test_identical_content_bypasses_the_threshold(self, make_article):
        """Exact hash equality is identity, not similarity - it does not get a vote."""
        first = make_article(original_title="یک عنوان", content="متن")
        second = make_article(
            original_title="عنوانی کاملا متفاوت و بی‌ربط",
            content="متن",
            content_hash=first.content_hash,
        )
        match = dedupe.find_duplicate(second)
        assert match is not None
        assert match.reason == "content_hash" and match.score == 1.0

    def test_encoding_variants_of_one_story_collide(self, make_article):
        """Arabic vs Persian YEH produced the same outlet under two spellings in the legacy
        database. Folding happens before hashing so the two are one story here."""
        first = make_article(original_title="گزارش ايسنا", content="متن یکسان")
        second = make_article(original_title="گزارش ایسنا", content="متن یکسان")
        assert first.content_hash == second.content_hash


class TestCanonicalChoice:
    def test_a_classified_article_is_never_demoted(self, make_article, variant):
        """An article already paid for must survive as canonical. Demoting it detaches the
        inference from the surviving id and lets a later, cheaper run replace a real result
        with a cruder one."""
        incumbent = make_article(original_title="حمله به تاسیسات", content="short")
        Classification.objects.create(
            article=incumbent, variant=variant, prompt_version=variant.prompt_version,
            provider="gapgpt", model="m", category="security",
        )
        newcomer = make_article(
            original_title="حمله به تاسیسات",
            content="a much longer body that would otherwise win the tiebreak" * 5,
            content_hash=incumbent.content_hash,
        )
        dedupe.resolve(newcomer)
        newcomer.refresh_from_db()
        incumbent.refresh_from_db()
        assert newcomer.duplicate_of_id == incumbent.pk
        assert incumbent.duplicate_of_id is None

    def test_lower_priority_source_wins(self, make_article, source):
        better = Source.objects.create(
            name="khabarfoori", strategy=Strategy.LISTING_DETAIL,
            url="https://example.com", priority=1,
        )
        weak = make_article(original_title="یک خبر مشترک", content="x")
        strong = make_article(
            original_title="یک خبر مشترک", content="x", source=better,
            content_hash=weak.content_hash,
        )
        dedupe.resolve(strong)
        weak.refresh_from_db()
        strong.refresh_from_db()
        assert strong.duplicate_of_id is None and weak.duplicate_of_id == strong.pk

    def test_longer_content_breaks_a_priority_tie(self, make_article):
        """Shahrekhabar listings often carry an empty body; the fuller copy is the story."""
        thin = make_article(original_title="خبر مشترک", content="")
        full = make_article(
            original_title="خبر مشترک", content="متن کامل و مفصل", content_hash=thin.content_hash
        )
        dedupe.resolve(full)
        thin.refresh_from_db()
        assert thin.duplicate_of_id == full.pk


class TestChainDepth:
    def test_the_chain_never_grows_past_one_level(self, make_article):
        """`duplicate_of IS NULL` has to stay a reliable "this is the story" filter. If a
        demoted canonical kept its own followers, some articles would point at a duplicate
        and vanish from every canonical query."""
        first = make_article(original_title="خبر تکراری", content="a")
        second = make_article(original_title="خبر تکراری", content="a", content_hash=first.content_hash)
        dedupe.resolve(second)
        third = make_article(
            original_title="خبر تکراری",
            content="متن بسیار کامل‌تر" * 20,
            content_hash=first.content_hash,
        )
        dedupe.resolve(third)

        for article in Article.objects.all():
            if article.duplicate_of_id:
                parent = Article.objects.get(pk=article.duplicate_of_id)
                assert parent.duplicate_of_id is None, "chain deeper than one level"
        assert Article.objects.canonical().count() == 1


class TestUndatedArticles:
    def test_undated_articles_still_get_candidates(self, make_article):
        """Shahrekhabar produces these routinely. Returning no candidates would skip them
        past dedup entirely, which is what used to happen."""
        make_article(original_title="خبر بدون تاریخ")
        undated = make_article(original_title="خبر بدون تاریخ دیگر", published_at=None)
        assert list(dedupe.candidates(undated)), "undated article must fall back to recent rows"

    def test_undated_duplicate_is_detected(self, make_article):
        first = make_article(original_title="سقوط بالگرد در استان فارس", published_at=None)
        second = make_article(
            original_title="سقوط بالگرد در استان فارس", published_at=None,
            content_hash=first.content_hash,
        )
        assert dedupe.find_duplicate(second) is not None


class TestWindowBlocking:
    def test_title_similarity_does_not_reach_outside_the_window(self, make_article):
        """Time-window blocking is what keeps this from an O(n^2) corpus scan. Two
        similarly-titled stories 41 hours apart are usually two different events."""
        from datetime import timedelta

        old = timezone.now() - timedelta(hours=dedupe.WINDOW_HOURS + 5)
        make_article(
            original_title="عنوان یکسان برای آزمون", content="متن اول", published_at=old
        )
        recent = make_article(original_title="عنوان یکسان برای آزمون", content="متن دوم")
        assert dedupe.find_duplicate(recent) is None

    def test_exact_hash_match_deliberately_ignores_the_window(self, make_article):
        """Identity is not similarity. The same bytes republished three days later is the
        same story, and the window must not hide that."""
        from datetime import timedelta

        old = timezone.now() - timedelta(hours=dedupe.WINDOW_HOURS + 48)
        first = make_article(original_title="خبر بازنشر شده", content="متن", published_at=old)
        second = make_article(
            original_title="خبر بازنشر شده", content="متن", content_hash=first.content_hash
        )
        match = dedupe.find_duplicate(second)
        assert match is not None and match.reason == "content_hash"


class TestBackfillSweep:
    def test_dry_run_reports_each_pair_once(self, make_article):
        """Without claim-tracking the same pair reports twice, once from each side, and the
        count comes out double."""
        first = make_article(original_title="خبر یکسان", content="x")
        make_article(original_title="خبر یکسان", content="x", content_hash=first.content_hash)
        pairs = dedupe.backfill(dry_run=True)
        assert len(pairs) == 1

    def test_dry_run_changes_nothing(self, make_article):
        first = make_article(original_title="خبر یکسان", content="x")
        second = make_article(
            original_title="خبر یکسان", content="x", content_hash=first.content_hash
        )
        dedupe.backfill(dry_run=True)
        second.refresh_from_db()
        assert second.duplicate_of_id is None


class TestCandidateCost:
    """The dedup sweep runs once per stored article, so anything loaded per candidate is
    multiplied by the size of the corpus."""

    def test_candidates_do_not_carry_the_article_body(self, make_article):
        """`find_duplicate` reads nothing off a candidate but its title.

        `content` was in the deferred-field list, so every candidate in a 36-hour window
        arrived with its full body attached - megabytes across the connection to compute a
        trigram set over a headline, once per article in the nightly backfill. Nothing in
        the response or in any other assertion would ever show it.
        """
        subject = make_article(original_title="عنوان اول")
        make_article(original_title="عنوان دوم", content="ب" * 5000)

        candidate = dedupe.candidates(subject).first()
        assert candidate is not None
        assert "content" in candidate.get_deferred_fields()

    def test_the_matched_row_is_still_compared_on_content_length(self, make_article):
        """The tiebreak that DOES need the body still works: `link()` re-fetches the one
        row that matched, rather than relying on the candidate scan to have carried it."""
        long_copy = make_article(original_title="حمله به تاسیسات نفتی", content="ب" * 4000)
        short_copy = make_article(original_title="حمله به تاسیسات نفتی", content="ب" * 10)

        assert dedupe.better_canonical(long_copy, short_copy)
        dedupe.resolve(short_copy)
        short_copy.refresh_from_db()
        assert short_copy.duplicate_of_id == long_copy.pk
