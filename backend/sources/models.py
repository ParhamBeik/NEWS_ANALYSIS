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
