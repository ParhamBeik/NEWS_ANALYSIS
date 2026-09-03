"""Carry the legacy SQLite corpus into Postgres.

WHAT COMES ACROSS: articles, their duplicate links, and the review cases.

WHAT DOES NOT: every classification, evaluation and summary. That is not laziness, it is
the finding that justified the rebuild. Of 1,139 stored classifications, 1,137 came from
the offline `rule` keyword baseline, and `RuleProvider` hardcoded «زیاد» - which is why
716 of 716 evaluations said "notify". Importing them would seed the golden set and every
/kpi denominator with the output of a keyword matcher wearing a model's clothes.

The remaining 2 rows ARE real GapGPT answers, and they are dropped too. A corpus where
two of 1,143 articles carry a verdict from a superseded model on a superseded prompt is
harder to reason about than one where none do, and re-running them costs $0.0005.

The review cases DO come across, including the one approved human label. Human judgement
is the scarcest thing in this system and the only thing here that cannot be regenerated.

Idempotent: matches on URL, so a re-run updates rather than duplicates.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone as djtz

from articles.models import Article, ExtractionTier
from core.text import content_hash
from review.models import ReviewCase, ReviewStatus
from sources.models import Source


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class Command(BaseCommand):
    help = "Import articles and review cases from the legacy SQLite database."

    def add_arguments(self, parser):
        parser.add_argument("--db", default="var/news.db", help="Path to the legacy SQLite file.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be imported and change nothing.",
        )

    def handle(self, *args, **options):
        path = Path(options["db"])
        if not path.exists():
            raise CommandError(f"legacy database not found at {path}")

        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row

        known_sources = set(Source.objects.values_list("name", flat=True))
        rows = list(connection.execute("SELECT * FROM articles ORDER BY id"))
        cases = list(connection.execute("SELECT * FROM review_cases ORDER BY id"))

        missing = {row["source"] for row in rows} - known_sources
        if missing:
            # A FK error 900 rows into a transaction tells you nothing useful. Fail before
            # touching anything, naming the fix.
            raise CommandError(
                f"legacy articles reference unknown sources {sorted(missing)}. "
                f"Run `manage.py seed_sources` first."
            )

        self.stdout.write(
            f"{len(rows)} articles, {len(cases)} review cases "
            f"({sum(case['status'] == 'approved' for case in cases)} approved)"
        )
        dropped = connection.execute(
            "SELECT (SELECT count(*) FROM classifications) + (SELECT count(*) FROM evaluations)"
            " + (SELECT count(*) FROM summaries)"
        ).fetchone()[0]
        self.stdout.write(
            self.style.WARNING(
                f"dropping {dropped} legacy inference rows - see this file's docstring"
            )
        )

        if options["dry_run"]:
            self.stdout.write("dry run; nothing written")
            return

        created = updated = 0
        # legacy id -> new id, so the second pass can rebuild the duplicate chain. Built
        # in a first pass because a duplicate may point at an article imported later.
        id_map: dict[int, int] = {}

        with transaction.atomic():
            for row in rows:
                title, lead, body = (
                    row["original_title"] or "",
                    row["lead"] or "",
                    row["content"] or "",
                )
                fields = {
                    "source_id": row["source"],
                    "original_outlet": row["original_outlet"] or "",
                    "original_title": title,
                    "lead": lead,
                    "content": body,
                    "content_hash": row["content_hash"] or content_hash(title, lead, body),
                    "published_at": parse_dt(row["published_at_gregorian"]),
                    "published_at_jalali": row["published_at_persian"] or "",
                    "published_time": row["published_time"] or "",
                    "date_uncertain": bool(row["date_uncertain"]),
                    "fetched_at": parse_dt(row["fetched_at"]) or djtz.now(),
                    "first_seen_run": row["first_seen_run"] or "",
                    "last_seen_run": row["last_seen_run"] or "",
                    # The tier ladder is the early-warning signal for a site redesign, so
                    # an unrecognised legacy value falls to the WEAKEST tier rather than
                    # being guessed upward. Understating extraction quality is safe;
                    # overstating it hides a source that has quietly degraded.
                    "extraction_tier": (
                        row["extraction_tier"]
                        if row["extraction_tier"] in ExtractionTier.values
                        else ExtractionTier.LISTING
                    ),
                    "quality_flag": (row["quality_flags"] or "").split(",")[0][:64],
                }
                article, was_created = Article.objects.update_or_create(
                    url=row["url"], defaults=fields
                )
                id_map[row["id"]] = article.pk
                created += was_created
                updated += not was_created

            # Second pass: duplicate links, now that every id is known.
            links = 0
            for row in rows:
                if not row["duplicate_of"]:
                    continue
                canonical = id_map.get(row["duplicate_of"])
                if canonical is None:
                    continue
                Article.objects.filter(pk=id_map[row["id"]]).update(
                    duplicate_of_id=canonical, duplicate_reason="legacy"
                )
                links += 1

            imported_cases = skipped_cases = 0
            for case in cases:
                article_pk = id_map.get(case["article_id"])
                if article_pk is None:
                    skipped_cases += 1
                    continue
                ReviewCase.objects.update_or_create(
                    article_id=article_pk,
                    defaults={
                        "stratum": case["stratum"] or "legacy",
                        "status": case["status"] or ReviewStatus.PENDING,
                        "reviewed_category": case["reviewed_category"] or "",
                        # `or None`, never `or ""`: an axis the reviewer left blank must
                        # stay NULL. An empty string here is a sentinel, and a sentinel in
                        # the ground truth is worse than one in a prediction.
                        "confidence_occurrence": case["confidence_occurrence"] or None,
                        "gold_price_impact": case["gold_price_impact"] or None,
                        "security_relevance": case["security_relevance"] or None,
                        "gold_trend": case["gold_trend"] or None,
                        "one_line": case["one_line"] or "",
                        "reviewer_notes": case["reviewer_notes"] or "",
                        "reviewed_at": parse_dt(case["reviewed_at"]),
                    },
                )
                imported_cases += 1

        connection.close()
        self.stdout.write(
            self.style.SUCCESS(
                f"articles: {created} created, {updated} updated, {links} duplicate links\n"
                f"review cases: {imported_cases} imported, {skipped_cases} skipped "
                f"(article not in the legacy set)\n"
                f"inference: 0 imported, by design"
            )
        )
