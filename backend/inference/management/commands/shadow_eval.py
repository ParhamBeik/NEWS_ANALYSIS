"""Release gate: re-ask the decision backend about staff-labelled items.

Run after any prompt or model change, before trusting it:

    python manage.py shadow_eval --dry-run          # cost estimate, no provider call
    python manage.py shadow_eval --language fa --limit 200

Exits non-zero unless the verdict is pass. See core.shadow_eval.
"""

from django.core.management.base import BaseCommand, CommandError

from core import shadow_eval


class Command(BaseCommand):
    help = "Shadow-evaluate the decision backend against swipe reviews and grouping decisions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=None,
            help="at most this many reviews and this many grouping pairs",
        )
        parser.add_argument("--language", choices=shadow_eval.LANGUAGES, default="all")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="print the token and cost estimate only; nothing is asked",
        )

    def handle(self, *args, limit, language, dry_run, **options):
        if limit is not None and limit < 1:
            raise CommandError("--limit must be positive")
        if dry_run:
            reviews = shadow_eval.labelled_reviews(language, limit)
            groupings = shadow_eval.labelled_groupings(language, limit)
            estimate = shadow_eval.estimate(reviews, groupings)
            self.stdout.write(
                f"dry run: backend={estimate['backend']} reviews={len(reviews)} "
                f"grouping_pairs={len(groupings)} tokens_in~{estimate['tokens_in']} "
                f"tokens_out<={estimate['tokens_out']} cost<=${estimate['cost_usd']:.4f}"
            )
            return
        try:
            row = shadow_eval.run(language=language, limit=limit)
        except shadow_eval.EvalUnavailable as exc:
            raise CommandError(f"shadow eval not run: {exc}") from exc
        overall, grouping = row.metrics["overall"], row.metrics["grouping"]
        self.stdout.write(
            f"eval {row.id}: {row.backend} {row.model} questions={row.question_hash[:12]} "
            f"labelled={row.labelled} grouping_pairs={row.grouping_pairs} failed={row.failed} "
            f"cost=${float(row.cost_usd):.4f}"
        )
        self.stdout.write(
            f"topic={overall['topic_accuracy']} iran_within_one={overall['iran_tier_within_one']} "
            f"global_within_one={overall['global_tier_within_one']} "
            f"grouping_precision={grouping['precision']} grouping_recall={grouping['recall']}"
        )
        if row.verdict != row.Verdict.PASS:
            raise CommandError(f"shadow eval {row.verdict}: " + "; ".join(row.reasons))
        self.stdout.write(self.style.SUCCESS("shadow eval passed"))
