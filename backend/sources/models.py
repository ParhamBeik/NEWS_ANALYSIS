"""The source registry.

A source is configuration, not code. Adding a site that fits an existing `strategy` is a
row; only a genuinely new page shape adds a handler in `sources.strategies`. Health lives
here too, so `/ops` can answer "is each source still alive?" without a crawl.
"""

from __future__ import annotations

from django.db import models


class Strategy(models.TextChoices):
    """How a source is crawled. The value keys `sources.strategies.REGISTRY`."""

    RSS_SABA = "rss_saba", "Saba/Nastooh CMS RSS (Mehr, IRNA, ISNA)"
    LISTING_DETAIL = "listing_detail", "Listing page -> detail page"
    LISTING_RELAY = "listing_relay", "Listing page -> interstitial -> real article"


class HealthStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    HEALTHY = "healthy", "Healthy"
    DEGRADED = "degraded", "Degraded"


class Source(models.Model):
    name = models.SlugField(primary_key=True, max_length=64)
    display_name = models.CharField(max_length=128, blank=True)
    strategy = models.CharField(max_length=32, choices=Strategy)
    url = models.URLField(max_length=500)
    # Separate from `url` because a feed and an archive are unrelated endpoints: Mehr's RSS
    # carries no history at all. Blank means this source cannot backfill, and /ops says so
    # rather than reporting a gap it will never close.
    archive_url = models.URLField(max_length=500, blank=True)
    tier = models.PositiveSmallIntegerField(default=2)
    # Lower wins when the same story arrives from several sources; ranks by how complete
    # that source's copy tends to be. See articles.dedupe.better_canonical.
    priority = models.PositiveSmallIntegerField(default=50)
    enabled = models.BooleanField(default=True)

    health_status = models.CharField(
        max_length=16, choices=HealthStatus, default=HealthStatus.UNKNOWN
    )
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "name"]

    def __str__(self) -> str:
        return self.display_name or self.name

    @property
    def supports_backfill(self) -> bool:
        return bool(self.archive_url)

    def mark_healthy(self) -> None:
        from django.utils import timezone

        Source.objects.filter(pk=self.pk).update(
            health_status=HealthStatus.HEALTHY,
            last_success_at=timezone.now(),
            last_error="",
        )

    def mark_degraded(self, error: str) -> None:
        """One source failing marks it degraded; the cycle continues with the others."""
        Source.objects.filter(pk=self.pk).update(
            health_status=HealthStatus.DEGRADED, last_error=str(error)[:2000]
        )


class PrefilterRule(models.Model):
    """A newsroom desk whose output is not worth a paid inference call.

    The Saba CMS publishes its own taxonomy slug on every item (`<category domain="soccer">`),
    and roughly 37% of everything crawled classifies as `other` - each one after paying for
    it. Matching the slug skips the spend.

    This is the one optimisation in the system that can silently lose a real story, so it
    is built to be audited rather than trusted:

    - the article is still fetched, extracted and STORED in full; only spending is withheld
    - the reason is recorded on the article, and /ops reports counts per rule
    - `enabled` is a switch, and `sources.prefilter.reapply` re-evaluates stored articles
      when a rule changes, so turning one off actually releases what it held back
    - rules are per-slug and explicit; there is no pattern matching and no default-deny

    Rules are scoped PER SOURCE because the slug vocabularies are not shared. Measured
    against the three live feeds: Mehr emits CamelCase desk names (`Hamedan`,
    `OtherMagazine`), IRNA emits lowercase names plus opaque abbreviations (`sb`, `atf`,
    `mfa`), and ISNA emits bare numeric ids (`8001`, `7001`) mixed with names. The same
    string means different things at different newsrooms, so a global list would suppress
    the wrong desk at two of the three.

    Nothing is enabled by seed. A filter you have not measured is a guess with a cost
    ceiling attached; `sources.prefilter.observed_slugs` exists so a rule can be switched
    on against evidence that the desk really does produce only `other`.
    """

    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.CASCADE, related_name="prefilter_rules",
        help_text="Leave empty only for a slug you have verified means the same thing everywhere.",
    )
    native_category = models.SlugField(max_length=64)
    label = models.CharField(max_length=128, blank=True)
    enabled = models.BooleanField(default=False)
    note = models.TextField(blank=True, help_text="Why this desk is not worth a paid call.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["source_id", "native_category"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "native_category"], name="unique_prefilter_rule"
            ),
            models.UniqueConstraint(
                fields=["native_category"],
                condition=models.Q(source__isnull=True),
                name="unique_global_prefilter_rule",
            ),
        ]

    def __str__(self) -> str:
        scope = self.source_id or "all sources"
        return f"{scope}/{self.native_category} ({'on' if self.enabled else 'off'})"

    @property
    def reason(self) -> str:
        return f"native_category:{self.native_category}"
