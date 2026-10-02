"""Load the watch-item vocabulary from YAML.

Upsert by slug. Items missing from the fixture are disabled, never deleted: events keep
their tags, and a re-enabled item picks up where it left off.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from articles.models import WatchItem

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "watch_items.yaml"


class Command(BaseCommand):
    help = "Create or update WatchItem rows from a YAML fixture."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(DEFAULT_FIXTURE))

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"fixture not found: {path}")
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(document, dict):
            raise CommandError(f"{path} must contain a mapping of slug -> item")
        kinds = set(WatchItem.Kind.values)
        for slug, entry in document.items():
            if entry.get("kind") not in kinds or not entry.get("en") or not entry.get("fa"):
                raise CommandError(f"{slug}: needs kind ({sorted(kinds)}), en and fa")
            aliases = entry.get("aliases") or []
            if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                raise CommandError(f"{slug}: aliases must be a list of strings")
            WatchItem.objects.update_or_create(
                slug=slug,
                defaults={
                    "kind": entry["kind"],
                    "name_en": entry["en"],
                    "name_fa": entry["fa"],
                    "aliases": aliases,
                    "enabled": entry.get("enabled", True),
                },
            )
        disabled = WatchItem.objects.exclude(slug__in=document).update(enabled=False)
        self.stdout.write(
            self.style.SUCCESS(f"{len(document)} watch items loaded, {disabled} disabled")
        )
