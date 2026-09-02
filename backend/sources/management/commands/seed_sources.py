"""Load the source registry from YAML.

Upsert rather than replace: re-running after editing the fixture updates configuration
without touching health history or orphaning the articles that point at a source.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

from sources.models import Source, Strategy

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sources.yaml"


class Command(BaseCommand):
    help = "Create or update Source rows from a YAML fixture."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(DEFAULT_FIXTURE))
        parser.add_argument(
            "--disable-missing",
            action="store_true",
            help="Disable sources absent from the fixture instead of leaving them alone.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"fixture not found: {path}")
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(document, dict):
            raise CommandError(f"{path} must contain a mapping of name -> source")

        valid = set(Strategy.values)
        created_count = 0
        for name, entry in document.items():
            strategy = entry.get("strategy")
            if strategy not in valid:
                # A typo would otherwise create a source that every crawl rejects at
                # dispatch time, looking like a site outage rather than a config error.
                raise CommandError(
                    f"{name}: unknown strategy {strategy!r}; choose from {sorted(valid)}"
                )
            _, created = Source.objects.update_or_create(
                name=name,
                defaults={
                    "display_name": entry.get("display_name", ""),
                    "strategy": strategy,
                    "url": entry["url"],
                    "archive_url": entry.get("archive_url", ""),
                    "tier": entry.get("tier", 2),
                    "priority": entry.get("priority", 50),
                    "enabled": entry.get("enabled", True),
                },
            )
            created_count += created
            self.stdout.write(f"  {'created' if created else 'updated'} {name}")

        if options["disable_missing"]:
            stale = Source.objects.exclude(name__in=document).filter(enabled=True)
            for source in stale:
                self.stdout.write(self.style.WARNING(f"  disabling {source.name}"))
            stale.update(enabled=False)

        total = len(document)
        self.stdout.write(
            self.style.SUCCESS(
                f"{total} sources ({created_count} new, {total - created_count} updated)"
            )
        )
