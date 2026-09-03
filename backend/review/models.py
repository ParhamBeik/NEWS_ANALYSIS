"""Human judgement: gold labels, and blinded A/B preferences.

Two different kinds of feedback, deliberately in two tables because they mean different
things and are used for different purposes:

- `ReviewCase`  "what was the RIGHT answer?" - absolute truth. Feeds /kpi agreement
                metrics, the golden set, and retrieval memory.
- `ABFeedback`  "which of these two was BETTER?" - relative preference. Feeds the choice
                of variant, and is the shape that later trains a reward model.

Storing a preference as though it were truth would let "B beat A" masquerade as "B was
correct", which it is not: both arms can be wrong.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models

from core.vocabulary import Category, GoldTrend, Level


class ReviewStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    SKIPPED = "skipped", "Skipped"


class ReviewCase(models.Model):
    """One article queued for labelling, and the label if it has been given.

    Every score field is nullable with no default, for the same reason as `Evaluation`:
    a reviewer leaving an axis blank means "not assessed", and writing a level there
    instead would poison the very ground truth the model is measured against.
    """

    article = models.OneToOneField(
        "articles.Article", on_delete=models.CASCADE, related_name="review_case"
    )
    # Why this article was worth a human's time: prompt disagreement, an `other` verdict,
    # an unevaluated row, or category round-robin. Recorded so /kpi can report agreement
    # per stratum rather than as one number over a non-random sample.
    stratum = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=16, choices=ReviewStatus, default=ReviewStatus.PENDING)

    reviewed_category = models.CharField(max_length=32, choices=Category, blank=True)
    confidence_occurrence = models.CharField(max_length=16, choices=Level, null=True, blank=True)
    gold_price_impact = models.CharField(max_length=16, choices=Level, null=True, blank=True)
    security_relevance = models.CharField(max_length=16, choices=Level, null=True, blank=True)
    gold_trend = models.CharField(max_length=16, choices=GoldTrend, null=True, blank=True)
    one_line = models.TextField(blank=True)
    reviewer_notes = models.TextField(blank=True)

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="review_cases",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["status", "stratum"])]

    def __str__(self) -> str:
        return f"review {self.pk} ({self.status})"

    @property
    def is_usable_truth(self) -> bool:
        """Only approved rows with a category count. A golden set seeded from the model's
        own answers would measure the model against itself and report perfect agreement."""
        return self.status == ReviewStatus.APPROVED and bool(self.reviewed_category)


class Side(models.TextChoices):
    A = "a", "Variant A"
    B = "b", "Variant B"


class Winner(models.TextChoices):
    LEFT = "left", "Left"
    RIGHT = "right", "Right"
    TIE = "tie", "Tie"


class ABPair(models.Model):
    """One blinded head-to-head between two variants on the same article.

    `shown_as_left` is randomised at creation and NEVER serialised to the client. The
    reviewer sees "left" and "right" with no model names, so the judgement cannot be
    biased by knowing which arm is the expensive one - and because the mapping is stored,
    position bias itself becomes measurable afterwards.
    """

    article = models.ForeignKey(
        "articles.Article", on_delete=models.CASCADE, related_name="ab_pairs"
    )
    variant_a = models.ForeignKey(
        "inference.PromptVariant", on_delete=models.CASCADE, related_name="pairs_as_a"
    )
    variant_b = models.ForeignKey(
        "inference.PromptVariant", on_delete=models.CASCADE, related_name="pairs_as_b"
    )
    shown_as_left = models.CharField(max_length=1, choices=Side, default=Side.A)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["article", "variant_a", "variant_b"], name="unique_ab_pair"
            ),
            models.CheckConstraint(
                condition=~models.Q(variant_a=models.F("variant_b")),
                name="ab_pair_variants_differ",
            ),
        ]

    def __str__(self) -> str:
        return f"pair {self.pk}: {self.variant_a_id} vs {self.variant_b_id}"

    @staticmethod
    def random_side() -> str:
        """secrets, not random: a predictable left/right sequence is a bias a reviewer can
        learn without noticing."""
        return secrets.choice([Side.A, Side.B])

    def variant_on(self, position: str):
        """Resolve a screen position back to the variant that occupied it."""
        left_is_a = self.shown_as_left == Side.A
        if position == Winner.LEFT:
            return self.variant_a if left_is_a else self.variant_b
        return self.variant_b if left_is_a else self.variant_a


class ABFeedback(models.Model):
    """A human preference over one blinded pair. Stored raw; interpretation happens later."""

    pair = models.ForeignKey(ABPair, on_delete=models.CASCADE, related_name="feedback")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ab_feedback"
    )
    winner = models.CharField(max_length=8, choices=Winner)
    reasoning = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One judgement per person per pair; a second submission is an edit, not a vote.
            models.UniqueConstraint(fields=["pair", "user"], name="unique_ab_feedback_per_user"),
        ]

    def __str__(self) -> str:
        return f"feedback on pair {self.pair_id}: {self.winner}"

    @property
    def winning_variant(self):
        """None on a tie. Resolves the blinded position to the actual variant."""
        if self.winner == Winner.TIE:
            return None
        return self.pair.variant_on(self.winner)
