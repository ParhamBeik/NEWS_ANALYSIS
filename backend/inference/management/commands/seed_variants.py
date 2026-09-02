"""Create the default prompt variants: the control arm and its memory challenger.

Only the control is active by default. Activating a second variant doubles the cost of
every cycle, because both arms answer every article - that is what produces the paired
output the A/B tab compares, and it should be a deliberate act rather than a default.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from inference.models import MemoryStrategy, PromptVariant

VARIANTS = [
    {
        "name": "control",
        "description": (
            "No retrieved context. The article and the policy, nothing else. This is the "
            "baseline every memory strategy has to beat, and it has to stay cheap to run."
        ),
        "memory_strategy": MemoryStrategy.NONE,
        "memory_k": 0,
        "is_active": True,
    },
    {
        "name": "semantic-memory",
        "description": (
            "Top-3 semantically nearest PAST articles with their verdicts, human-reviewed "
            "first. Activate alongside control to generate A/B pairs; costs roughly double "
            "per cycle plus a larger prompt."
        ),
        "memory_strategy": MemoryStrategy.SEMANTIC,
        "memory_k": 3,
        "is_active": False,
    },
    {
        "name": "trigram-memory",
        "description": (
            "The pre-embedding baseline: nearest approved labels by title trigram overlap. "
            "Worth keeping as an arm - if it matches semantic retrieval, the embedding "
            "spend buys nothing."
        ),
        "memory_strategy": MemoryStrategy.TRIGRAM,
        "memory_k": 3,
        "is_active": False,
    },
    {
        "name": "semantic-market",
        "description": (
            "Semantic neighbours plus the last gold and dollar prices with their weekly "
            "change. Tests whether market context improves gold-impact calibration."
        ),
        "memory_strategy": MemoryStrategy.SEMANTIC_MARKET,
        "memory_k": 3,
        "is_active": False,
    },
]


class Command(BaseCommand):
    help = "Create or update the default prompt variants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model", default="", help="Override the model for every seeded variant."
        )

    def handle(self, *args, **options):
        model = options["model"] or settings.GAPGPT_MODEL
        for spec in VARIANTS:
            defaults = {
                "description": spec["description"],
                "provider": "gapgpt",
                "model": model,
                "memory_strategy": spec["memory_strategy"],
                "memory_k": spec["memory_k"],
            }
            # `is_active` is seeded on creation only. Re-seeding must never flip it: doing
            # so during a running experiment would silently change what a cycle costs and
            # orphan the half-collected A/B pairs.
            if not PromptVariant.objects.filter(name=spec["name"]).exists():
                defaults["is_active"] = spec["is_active"]
            variant, created = PromptVariant.objects.update_or_create(
                name=spec["name"], defaults=defaults
            )
            state = "active" if variant.is_active else "inactive"
            self.stdout.write(
                f"  {'created' if created else 'updated'} {variant.name} "
                f"({variant.memory_strategy}, {state})"
            )
        from inference.prompts import prompt_version

        active = PromptVariant.objects.filter(is_active=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(VARIANTS)} variants on model {model} at prompt {prompt_version()}; "
                f"{active} active (each active variant answers every article)"
            )
        )
