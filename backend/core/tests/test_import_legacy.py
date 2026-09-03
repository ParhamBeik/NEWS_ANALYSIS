"""The legacy import, against a synthetic SQLite file with the real schema.

Two things are worth locking, and both are about what must NOT come across:

1. **No inference.** 1,137 of the legacy corpus's 1,139 classifications came from an
   offline keyword matcher that hardcoded «زیاد», which is why every one of its 716
   evaluations said "notify". Importing them would seed the golden set and every /kpi
   denominator with a keyword matcher wearing a model's clothes.
2. **A blank human axis stays NULL.** `or ""` instead of `or None` on that line would put
   a sentinel into the ground truth - worse than a bad prediction, because a prediction
   can be re-run and a corrupted label cannot be recovered.
"""

from __future__ import annotations

import sqlite3

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from articles.models import Article
from inference.models import Classification, Evaluation, Summary
from review.models import ReviewCase, ReviewStatus

SCHEMA = """
CREATE TABLE articles (
  id INTEGER PRIMARY KEY, url TEXT, identity_key TEXT, source TEXT, original_outlet TEXT,
  original_title TEXT, lead TEXT, content TEXT, content_hash TEXT,
  published_at_gregorian TEXT, published_at_persian TEXT, published_time TEXT,
  date_uncertain INTEGER, fetched_at TEXT, first_seen_run TEXT, last_seen_run TEXT,
  extraction_tier TEXT, quality_flags TEXT, duplicate_of INTEGER);
CREATE TABLE review_cases (
  id INTEGER PRIMARY KEY, article_id INTEGER, stratum TEXT, status TEXT,
  reviewed_category TEXT, confidence_occurrence TEXT, gold_price_impact TEXT,
  security_relevance TEXT, gold_trend TEXT, one_line TEXT, reviewer_notes TEXT,
  reviewed_at TEXT, created_at TEXT);
CREATE TABLE classifications (id INTEGER PRIMARY KEY, provider TEXT);
CREATE TABLE evaluations (id INTEGER PRIMARY KEY, provider TEXT);
CREATE TABLE summaries (id INTEGER PRIMARY KEY, provider TEXT);
"""


@pytest.fixture
def legacy_db(tmp_path, source):
    path = tmp_path / "news.db"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.executemany(
        "INSERT INTO articles (id, url, source, original_outlet, original_title, lead, "
        "content, content_hash, published_at_gregorian, published_at_persian, "
        "published_time, date_uncertain, fetched_at, extraction_tier, quality_flags, "
        "duplicate_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "https://www.mehrnews.com/news/legacy-1", source.name, "مهر", "تیتر یک",
             "خلاصه", "متن", "hash1", "2026-08-18T10:00:00+00:00", "1405-05-27", "10:00",
             0, "2026-08-18T11:00:00+00:00", "jsonld", None, None),
            (2, "https://www.mehrnews.com/news/legacy-2", source.name, "مهر", "تیتر دو",
             "خلاصه", "متن", "hash2", "2026-08-18T10:30:00+00:00", "1405-05-27", "10:30",
             0, "2026-08-18T11:00:00+00:00", "css", None, 1),
            # An extraction tier the new enum does not know about.
            (3, "https://www.mehrnews.com/news/legacy-3", source.name, "مهر", "تیتر سه",
             "", "", "hash3", None, "1405-05-26", "", 1, "2026-08-18T11:00:00+00:00",
             "some-old-tier", None, None),
        ],
    )
    connection.executemany(
        "INSERT INTO review_cases (id, article_id, stratum, status, reviewed_category, "
        "confidence_occurrence, gold_price_impact, security_relevance, gold_trend, "
        "one_line, reviewer_notes, reviewed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # An approved label with gold_price_impact deliberately unassessed.
            (1, 1, "disagreement", "approved", "security", "زیاد", None, "خیلی زیاد",
             "نامطمئن", "یک جمله", "", "2026-08-19T09:00:00+00:00"),
            (2, 2, "round_robin", "pending", None, None, None, None, None, "", "", None),
            # Points at an article that does not exist in this dump.
            (3, 999, "round_robin", "pending", None, None, None, None, None, "", "", None),
        ],
    )
    connection.executemany("INSERT INTO classifications (id, provider) VALUES (?,?)",
                           [(i, "rule") for i in range(1, 21)])
    connection.executemany("INSERT INTO evaluations (id, provider) VALUES (?,?)",
                           [(i, "rule") for i in range(1, 11)])
    connection.executemany("INSERT INTO summaries (id, provider) VALUES (?,?)",
                           [(i, "rule") for i in range(1, 6)])
    connection.commit()
    connection.close()
    return path


@pytest.mark.django_db
class TestImportLegacy:
    def test_articles_and_duplicate_links_come_across(self, legacy_db):
        call_command("import_legacy", "--db", str(legacy_db))
        assert Article.objects.count() == 3
        duplicate = Article.objects.get(url__endswith="legacy-2")
        canonical = Article.objects.get(url__endswith="legacy-1")
        assert duplicate.duplicate_of == canonical
        assert duplicate.duplicate_reason == "legacy"

    def test_no_inference_is_imported(self, legacy_db):
        """The finding that justified the rebuild: the legacy verdicts are a keyword
        matcher's output, and 716 of 716 of them said "notify"."""
        call_command("import_legacy", "--db", str(legacy_db))
        assert Classification.objects.count() == 0
        assert Evaluation.objects.count() == 0
        assert Summary.objects.count() == 0

    def test_an_unassessed_human_axis_stays_null(self, legacy_db):
        """`or ""` on that line would write a sentinel into the ground truth. A bad
        prediction can be re-run; a corrupted label cannot be recovered."""
        call_command("import_legacy", "--db", str(legacy_db))
        case = ReviewCase.objects.get(status=ReviewStatus.APPROVED)
        assert case.gold_price_impact is None
        assert case.confidence_occurrence == "زیاد"
        assert case.security_relevance == "خیلی زیاد"
        assert case.is_usable_truth

    def test_a_case_pointing_at_a_missing_article_is_skipped_not_fatal(self, legacy_db):
        call_command("import_legacy", "--db", str(legacy_db))
        assert ReviewCase.objects.count() == 2

    def test_an_unknown_extraction_tier_falls_to_the_weakest(self, legacy_db):
        """Understating extraction quality is safe. Guessing upward would hide a source
        that has quietly degraded, which is the one thing the tier exists to reveal."""
        call_command("import_legacy", "--db", str(legacy_db))
        assert Article.objects.get(url__endswith="legacy-3").extraction_tier == "listing"

    def test_running_twice_updates_rather_than_duplicates(self, legacy_db):
        call_command("import_legacy", "--db", str(legacy_db))
        call_command("import_legacy", "--db", str(legacy_db))
        assert Article.objects.count() == 3
        assert ReviewCase.objects.count() == 2

    def test_dry_run_writes_nothing(self, legacy_db):
        call_command("import_legacy", "--db", str(legacy_db), "--dry-run")
        assert Article.objects.count() == 0

    def test_an_unseeded_source_fails_before_anything_is_written(self, legacy_db):
        """A FK error 900 rows into a transaction tells you nothing. Fail up front, and
        name the command that fixes it."""
        from sources.models import Source

        Source.objects.all().delete()
        with pytest.raises(CommandError, match="seed_sources"):
            call_command("import_legacy", "--db", str(legacy_db))
        assert Article.objects.count() == 0

    def test_a_missing_file_is_a_clean_error(self, tmp_path):
        with pytest.raises(CommandError, match="not found"):
            call_command("import_legacy", "--db", str(tmp_path / "nope.db"))
