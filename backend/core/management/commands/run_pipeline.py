"""Run a pipeline stage on demand, from a shell.

Beat runs everything on a schedule, so this is not the normal path. It exists because the
abnormal paths are real: proving a fresh deployment works, backfilling after an outage,
re-running a stage whose bug you just fixed, and answering "is it the crawler or the
model?" without waiting up to thirty minutes for the next tick.

Without it the only way in is `manage.py shell` with an import line, which means the
operator has to know the task's module path and its keyword arguments - and gets a
traceback rather than an error message when they guess wrong.

Two modes, and the distinction matters:

  --queue  (default)  hand the task to Celery and return. This is what production looks
                      like, so it is what you want when proving the workers are wired up.
  --now               run it inline in this process. Use when the workers are the thing
                      you suspect - an inline run cannot be silently swallowed by a queue
                      nobody is consuming.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

STAGES = {
    "crawl": ("sources.tasks", "crawl_all"),
    "canary": ("sources.tasks", "canary"),
    "images": ("articles.tasks", "download_pending_images"),
    "dedupe": ("articles.tasks", "backfill_dedupe"),
    "prefilter": ("articles.tasks", "reapply_prefilter"),
    "embed": ("inference.tasks", "embed_missing"),
    "inference": ("inference.tasks", "run_cycle"),
    "finalize": ("inference.tasks", "finalize_stale_runs"),
    "prices": ("market.tasks", "poll_prices"),
    "backtest": ("market.tasks", "backtest_predictions"),
    "workbook": ("exports.tasks", "build_daily_workbook"),
    "sample-review": ("review.tasks", "sample_review_cases"),
    "ab-pairs": ("review.tasks", "build_ab_pairs"),
}


class Command(BaseCommand):
    help = "Run one pipeline stage now, either queued to Celery or inline."

    def add_arguments(self, parser):
        parser.add_argument("stage", choices=sorted(STAGES))
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Cap the number of items. Accepted only by stages that take one.",
        )
        parser.add_argument(
            "--now", action="store_true",
            help="Run inline instead of queueing. Use when you suspect the workers.",
        )

    def handle(self, *args, **options):
        stage = options["stage"]
        module_path, task_name = STAGES[stage]

        module = __import__(module_path, fromlist=[task_name])
        task = getattr(module, task_name, None)
        if task is None:
            raise CommandError(f"{module_path}.{task_name} does not exist")

        # Only pass `limit` where the task actually accepts it. Sending an unexpected
        # kwarg to a Celery task fails inside the worker, minutes later, in a log the
        # operator is not watching.
        kwargs = {}
        if options["limit"] is not None:
            accepted = task.run.__code__.co_varnames[: task.run.__code__.co_argcount]
            if "limit" not in accepted:
                raise CommandError(f"stage {stage!r} does not take --limit")
            kwargs["limit"] = options["limit"]

        if options["now"]:
            self.stdout.write(f"running {stage} inline...")
            result = task(**kwargs)
            payload = json.dumps(result, ensure_ascii=False, default=str)
            self.stdout.write(self.style.SUCCESS(payload))
            return

        async_result = task.delay(**kwargs)
        self.stdout.write(
            self.style.SUCCESS(f"queued {stage} as {async_result.id}")
        )
        self.stdout.write(
            "  watch it with:  docker compose -f docker-compose.prod.yml logs -f "
            "worker-crawl worker-inference"
        )
