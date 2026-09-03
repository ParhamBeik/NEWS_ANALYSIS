"""Install the periodic schedule into django-celery-beat.

DB-backed rather than a static dict, so a cadence can be changed from the admin without a
redeploy - which matters because the right crawl interval is an operational judgement that
will be tuned against real cost, not a constant discovered at design time.

Cadences and their reasons:

- crawl every 30 minutes, matching the legacy loop. Crawling is free; only inference costs.
- inference on its own 30-minute cycle, OFFSET from the crawl by design. Running them
  together means the inference pass reads a half-written corpus and pays again next cycle
  for what it missed.
- prices every 15 minutes: fine-grained enough that "the last price before publication" is
  actually close to publication, which is what makes the back-test baseline meaningful.
- back-test hourly. It is a cheap SQL sweep and it can only score predictions the market
  has had time to answer, so running it often costs nothing and shortens the feedback loop.
- workbook nightly at 23:50 Tehran, so the file covers the whole Jalali day it is named for.
- canary hourly: a source returning 200 with zero parsed articles is a redesign, and the
  sooner that is visible the fewer empty cycles get filed as normal.
- run finalisation every 10 minutes. A run whose books are never closed reports $0 spent
  forever, so the one table an operator reads for cost is the one that would lie.
- review sampling and A/B pairing hourly. Both queues are consumed by a human at their own
  pace; the cost of queueing a little ahead is a row, and the cost of queueing nothing is
  that every agreement metric on /kpi stays null.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

TEHRAN = "Asia/Tehran"

INTERVAL_TASKS = [
    ("crawl-all-sources", "sources.crawl_all", 30, IntervalSchedule.MINUTES, {}),
    ("inference-cycle", "inference.run_cycle", 30, IntervalSchedule.MINUTES, {}),
    ("embed-missing", "inference.embed_missing", 30, IntervalSchedule.MINUTES, {}),
    ("poll-market-prices", "market.poll_prices", 15, IntervalSchedule.MINUTES, {}),
    ("backtest-predictions", "market.backtest_predictions", 1, IntervalSchedule.HOURS, {}),
    ("source-canary", "sources.canary", 1, IntervalSchedule.HOURS, {}),
    ("download-pending-images", "articles.tasks.download_pending_images", 1,
     IntervalSchedule.HOURS, {}),
    # Offset from the 30-minute inference cycle by its own cadence: a run is finalised once
    # its tasks stop writing events, so sweeping more often than that just re-reads runs
    # that are still working.
    ("finalize-stale-runs", "inference.finalize_stale_runs", 10, IntervalSchedule.MINUTES, {}),
    ("sample-review-cases", "review.sample_review_cases", 1, IntervalSchedule.HOURS, {}),
    ("build-ab-pairs", "review.build_ab_pairs", 1, IntervalSchedule.HOURS, {}),
]

CRON_TASKS = [
    # 23:50 Tehran: late enough to include the day's last articles, early enough that the
    # file exists before anyone looks for it in the morning.
    ("nightly-workbook", "exports.build_daily_workbook", {"hour": "23", "minute": "50"}, {}),
    # Dedup sweep at 03:00, when nothing else is competing for the worker.
    ("nightly-dedupe-sweep", "articles.tasks.backfill_dedupe", {"hour": "3", "minute": "0"},
     {"dry_run": False}),
]


class Command(BaseCommand):
    help = "Create or update the periodic task schedule."

    def add_arguments(self, parser):
        parser.add_argument(
            "--disable-all", action="store_true",
            help="Install the schedule but leave every task disabled.",
        )

    def handle(self, *args, **options):
        enabled = not options["disable_all"]

        for name, task, every, period, kwargs in INTERVAL_TASKS:
            schedule, _ = IntervalSchedule.objects.get_or_create(every=every, period=period)
            PeriodicTask.objects.update_or_create(
                name=name,
                defaults={
                    "task": task,
                    "interval": schedule,
                    "crontab": None,
                    "kwargs": json.dumps(kwargs),
                    "enabled": enabled,
                },
            )
            self.stdout.write(f"  {name:28} every {every} {period}")

        for name, task, cron, kwargs in CRON_TASKS:
            schedule, _ = CrontabSchedule.objects.get_or_create(
                minute=cron["minute"],
                hour=cron["hour"],
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
                timezone=TEHRAN,
            )
            PeriodicTask.objects.update_or_create(
                name=name,
                defaults={
                    "task": task,
                    "crontab": schedule,
                    "interval": None,
                    "kwargs": json.dumps(kwargs),
                    "enabled": enabled,
                },
            )
            self.stdout.write(f"  {name:28} at {cron['hour']}:{cron['minute']} {TEHRAN}")

        state = "enabled" if enabled else "DISABLED"
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(INTERVAL_TASKS) + len(CRON_TASKS)} periodic tasks installed ({state})"
            )
        )
