"""Inference storage, prompt variants, and run telemetry.

INFERENCE IS APPEND-ONLY. Classification, Evaluation and Summary are separate tables from
the article, each stamped with the variant, prompt version, provider and model that
produced it. Re-running with a new prompt ADDS a row rather than overwriting one. That is
the single property that makes A/B comparison possible at all - without it, "what did the
old prompt say?" has no answer.

`PromptVariant` is the unit of experiment. Memory-vs-no-memory is a row here, not a code
branch, so a new strategy is configuration and every stored answer records which strategy
produced it.
"""

from __future__ import annotations

import secrets
from datetime import datetime

from django.db import models
from django.utils import timezone

from core.vocabulary import Category, GoldTrend, Level


class MemoryStrategy(models.TextChoices):
    """What context, if any, is retrieved and shown to the model alongside the article.

    This is the A/B axis the whole retrieval stack exists to test. `NONE` is not a
    degenerate case - it is the control arm, and it has to stay cheap to run.
    """

    NONE = "none", "No memory (control arm)"
    TRIGRAM = "trigram", "Nearest approved labels by title trigram similarity"
    SEMANTIC = "semantic", "Nearest approved labels by embedding similarity"
    SEMANTIC_MARKET = "semantic+market", "Semantic neighbours plus recent market context"


class PromptVariant(models.Model):
    """One configuration under test: provider, model, memory strategy, prompt text."""

    name = models.SlugField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    provider = models.CharField(max_length=32, default="gapgpt")
    model = models.CharField(max_length=64)
    memory_strategy = models.CharField(
        max_length=32, choices=MemoryStrategy, default=MemoryStrategy.NONE
    )
    # How many retrieved neighbours to inject. Ignored when memory_strategy is NONE.
    memory_k = models.PositiveSmallIntegerField(default=3)
    # FROZEN INVARIANT 3/4: sha256 of the prompt policy files, never hand-maintained.
    # Recomputed from disk on save; see inference.prompts.prompt_version().
    prompt_version = models.CharField(max_length=16, editable=False)
    is_active = models.BooleanField(
        default=False, help_text="Active variants run on every cycle."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_active", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.provider}:{self.model}, {self.memory_strategy})"

    def save(self, *args, **kwargs):
        from .prompts import prompt_version

        self.prompt_version = prompt_version()
        return super().save(*args, **kwargs)

    @property
    def identity(self) -> tuple[str, str, str]:
        """What a stored row must match for "has this already been answered?" to be true."""
        return (self.provider, self.model, self.prompt_version)


class RunStatus(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    ABORTED = "aborted", "Aborted (budget or fatal)"


def new_run_id(now: datetime | None = None) -> str:
    """Sortable and unique.

    The random suffix is not decoration: run ids are unique and second resolution is not,
    so two runs starting in the same second collided on insert and took the whole run down
    with an integrity error.
    """
    stamp = (now or timezone.now()).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{secrets.token_hex(3)}"


class Run(models.Model):
    run_id = models.CharField(max_length=32, unique=True, default=new_run_id, editable=False)
    mode = models.CharField(max_length=32, default="pipeline")
    status = models.CharField(max_length=16, choices=RunStatus, default=RunStatus.RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    articles_fetched = models.PositiveIntegerField(default=0)
    articles_processed = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.run_id} ({self.status})"


class NodeStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    RETRY = "retry", "Retrying"
    EXHAUSTED = "exhausted", "Retries exhausted"
    PERMANENT = "permanent", "Permanent failure"
    FATAL = "fatal", "Fatal"
    SKIPPED = "skipped", "Skipped (already answered)"


class NodeEvent(models.Model):
    """One row per node execution: the telemetry `/ops` reads and the audit trail that
    proves a paid provider actually answered, rather than a silent fallback."""

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="events")
    node = models.CharField(max_length=32, db_index=True)
    article = models.ForeignKey(
        "articles.Article", null=True, blank=True, on_delete=models.CASCADE,
        related_name="node_events",
    )
    variant = models.ForeignKey(
        PromptVariant, null=True, blank=True, on_delete=models.SET_NULL, related_name="events"
    )
    status = models.CharField(max_length=16, choices=NodeStatus)
    attempt = models.PositiveSmallIntegerField(default=1)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    provider = models.CharField(max_length=32, blank=True)
    model = models.CharField(max_length=64, blank=True)
    error_class = models.CharField(max_length=32, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["run", "created_at"]),
            models.Index(fields=["node", "status"]),
        ]


class DeadLetter(models.Model):
    """A permanently failed node, quarantined instead of retried forever."""

    article = models.ForeignKey(
        "articles.Article", on_delete=models.CASCADE, related_name="dead_letters"
    )
    node = models.CharField(max_length=32)
    error_class = models.CharField(max_length=32)
    attempts = models.PositiveSmallIntegerField(default=1)
    last_error = models.TextField(blank=True)
    quarantined_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["article", "node"], name="unique_dead_letter"),
        ]
        indexes = [models.Index(fields=["resolved_at", "node"])]


# ------------------------------------------------------------------- inference results


class InferenceResultQuerySet(models.QuerySet):
    def latest_per_article(self):
        """The newest answer for each article, whatever produced it.

        Postgres DISTINCT ON does natively what the old SQLite schema emulated with three
        correlated-subquery views. Use `.latest_ids()` when the result needs re-ordering,
        because DISTINCT ON pins the ORDER BY.
        """
        return self.order_by("article_id", "-created_at", "-id").distinct("article_id")

    def latest_ids(self):
        return self.latest_per_article().values("pk")

    def for_variant(self, variant: PromptVariant):
        provider, model, prompt_version = variant.identity
        return self.filter(provider=provider, model=model, prompt_version=prompt_version)


class InferenceResult(models.Model):
    """Shared provenance. Every answer records what produced it, which is what makes the
    "already answered?" gate and A/B comparison work on the same columns."""

    article = models.ForeignKey(
        "articles.Article", on_delete=models.CASCADE, related_name="%(class)ss"
    )
    variant = models.ForeignKey(
        PromptVariant, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="%(class)ss",
    )
    prompt_version = models.CharField(max_length=16)
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=64)
    run = models.ForeignKey(
        Run, null=True, blank=True, on_delete=models.SET_NULL, related_name="%(class)ss"
    )
    rationale = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = InferenceResultQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class Classification(InferenceResult):
    category = models.CharField(max_length=32, choices=Category)
    confidence = models.CharField(max_length=16, choices=Level, blank=True)
    matched_keywords = models.JSONField(default=list, blank=True)

    class Meta(InferenceResult.Meta):
        abstract = False
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["article", "-created_at"])]


class Evaluation(InferenceResult):
    """The three ordinal scores that decide notification.

    Every score column is NULLABLE WITH NO DEFAULT. NULL means "not assessed" and must
    never be filled with a level - see core.scoring. The check constraint below mirrors the
    schema validator: an evaluation that assessed fewer than two axes cannot decide
    anything, so storing it as though it could is the failure mode being prevented.
    """

    confidence_occurrence = models.CharField(max_length=16, choices=Level, null=True, blank=True)
    gold_price_impact = models.CharField(max_length=16, choices=Level, null=True, blank=True)
    security_relevance = models.CharField(max_length=16, choices=Level, null=True, blank=True)
    gold_trend = models.CharField(max_length=16, choices=GoldTrend, null=True, blank=True)

    class Meta(InferenceResult.Meta):
        abstract = False
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["article", "-created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        confidence_occurrence__isnull=False, gold_price_impact__isnull=False
                    )
                    | models.Q(
                        confidence_occurrence__isnull=False, security_relevance__isnull=False
                    )
                    | models.Q(gold_price_impact__isnull=False, security_relevance__isnull=False)
                ),
                name="evaluation_assesses_at_least_two_axes",
            ),
        ]

    @property
    def decision(self):
        from core.scoring import decide

        return decide(
            self.confidence_occurrence, self.gold_price_impact, self.security_relevance
        )


class Summary(InferenceResult):
    optimized_title = models.TextField(blank=True)
    one_line = models.TextField(blank=True)

    class Meta(InferenceResult.Meta):
        abstract = False
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["article", "-created_at"])]
