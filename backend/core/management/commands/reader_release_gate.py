"""Read-only evidence gate for the public reader and browser alerts."""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from articles.models import EventReview
from core.events import priority_visibility
from inference import budget
from sources.models import HealthStatus, Source


class Command(BaseCommand):
    help = (
        "Report whether source coverage, timeliness, reviewed alert quality "
        "and cost meet release targets."
    )

    def add_arguments(self, parser):
        parser.add_argument("--min-reviewed", type=int, default=100)
        parser.add_argument("--min-priority-items", type=int, default=100)

    def handle(self, *args, **options):
        reviewed = list(
            EventReview.objects.filter(
                status=EventReview.Status.REVIEWED,
                reviewed_iran_score__isnull=False,
            ).select_related("event")
        )
        false_alerts = sum(
            (row.event.iran_score or 0) >= 80 and row.reviewed_iran_score < 80 for row in reviewed
        )
        missed = sum(
            (row.event.iran_score or 0) < 80 and row.reviewed_iran_score >= 80 for row in reviewed
        )
        predicted_top = sum((row.event.iran_score or 0) >= 80 for row in reviewed)
        actual_top = sum(row.reviewed_iran_score >= 80 for row in reviewed)
        visibility = priority_visibility()
        source_count = Source.objects.filter(enabled=True).count()
        healthy_count = Source.objects.filter(
            enabled=True,
            health_status=HealthStatus.HEALTHY,
            last_success_at__gte=timezone.now() - timedelta(hours=6),
        ).count()
        spent = budget.month_spend()
        self.stdout.write(
            f"sources={source_count}/25 healthy_recent={healthy_count}/25 "
            f"reviewed={len(reviewed)}/{options['min_reviewed']} "
            f"priority_items={visibility['sample_size']}/{options['min_priority_items']} "
            f"p95_minutes={visibility['p95_minutes']} monthly_ai_usd={spent:.4f}"
        )
        self.stdout.write(
            f"false_top_tier={false_alerts}/{predicted_top} missed_top_tier={missed}/{actual_top}"
        )
        failures = []
        if source_count < 25:
            failures.append("fewer than 25 enabled sources")
        if healthy_count < 25:
            failures.append("fewer than 25 sources crawled successfully in the last 6 hours")
        if len(reviewed) < options["min_reviewed"]:
            failures.append("reviewed sample is too small")
        if min(predicted_top, actual_top) < 10:
            failures.append("reviewed sample has too few top-tier cases")
        if visibility["sample_size"] < options["min_priority_items"] or (
            visibility["p95_minutes"] is None or visibility["p95_minutes"] > 10
        ):
            failures.append("priority-source visibility target is unverified or missed")
        if predicted_top and false_alerts / predicted_top > 0.02:
            failures.append("false top-tier rate exceeds 2%")
        if actual_top and missed / actual_top > 0.05:
            failures.append("missed top-tier rate exceeds 5%")
        if spent > 100:
            failures.append("monthly AI ceiling exceeded")
        if failures:
            raise CommandError("reader release gate failed: " + "; ".join(failures))
        self.stdout.write(self.style.SUCCESS("reader release gate passed"))
