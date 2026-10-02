"""The source registry.

A source is configuration, not code. Adding a site that fits an existing `strategy` is a
row; only a genuinely new page shape adds a handler in `sources.strategies`. Health lives
here too, so `/ops` can answer "is each source still alive?" without a crawl.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone

from core.errors import ERROR_CLASSES, Transient, classify_exception, error_class

logger = logging.getLogger(__name__)

ERROR_CLASS_CHOICES = [(name, name) for name in ERROR_CLASSES]


class CrawlAttempt(models.Model):
    """One task execution, including retries; counters survive a worker interruption."""

    source = models.ForeignKey("Source", on_delete=models.PROTECT, related_name="crawl_attempts")
    task_id = models.CharField(max_length=255, blank=True)
    retry = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, default="running", choices=[
        (state, state) for state in ("running", "success", "partial", "empty", "failed")
    ])
    fetched = models.PositiveIntegerField(default=0)
    new = models.PositiveIntegerField(default=0)
    repeated = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=255, blank=True)
    error_class = models.CharField(max_length=16, blank=True, choices=ERROR_CLASS_CHOICES)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [models.Index(fields=["source", "-started_at"])]

    def __str__(self):
        return f"{self.source_id}: {self.status} ({self.started_at})"


class CoverageInterval(models.Model):
    """When a source was watched, when it failed, and when nobody was looking.

    One row per run of the same outcome, not per crawl: a crawl every two minutes would
    write 720 rows a day per source, so a repeat outcome extends the latest row instead.
    Intervals are contiguous - a gap starts where the last covered stretch ended - so
    "how many hours did we miss" is a sum, not a reconstruction.

    `unknown` is the honest state for a silence longer than UNOBSERVED_AFTER: the worker
    or beat was down, so we cannot claim the source was covered or that it failed.
    """

    COVERED, GAP, UNKNOWN = "covered", "gap", "unknown"
    # Five crawl cadences (every 2 min, see setup_schedule) plus retry backoff headroom.
    UNOBSERVED_AFTER = timedelta(minutes=10)

    source = models.ForeignKey("Source", on_delete=models.PROTECT, related_name="coverage")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    state = models.CharField(max_length=8, choices=[(s, s) for s in (COVERED, GAP, UNKNOWN)])
    error_class = models.CharField(max_length=16, blank=True, choices=ERROR_CLASS_CHOICES)

    class Meta:
        ordering = ["-ended_at", "-id"]
        indexes = [models.Index(fields=["source", "-ended_at"])]

    def __str__(self):
        return f"{self.source_id}: {self.state} {self.started_at} - {self.ended_at}"

    @classmethod
    def record(cls, source, state: str, error_class: str = "", *, now=None) -> None:
        now = now or timezone.now()
        with transaction.atomic():
            last = cls.objects.select_for_update().filter(source=source).first()
            if last and now - last.ended_at > cls.UNOBSERVED_AFTER:
                cls.objects.create(
                    source=source, started_at=last.ended_at, ended_at=now, state=cls.UNKNOWN
                )
                last = None
            if last and (last.state, last.error_class) == (state, error_class):
                cls.objects.filter(pk=last.pk).update(ended_at=now)
                return
            cls.objects.create(
                source=source,
                started_at=last.ended_at if last else now,
                ended_at=now,
                state=state,
                error_class=error_class,
            )


class FetchRetry(models.Model):
    """An article page that failed for a reason worth trying again.

    The crawl itself retries the whole source (Celery autoretry), but a single detail page
    timing out was simply skipped: the story stayed at feed tier, or for listing sources
    was never stored at all. This row keeps that URL until `sources.drain_fetch_retries`
    succeeds or gives up, and it survives a worker restart because it lives in Postgres.
    Only transient failures are queued; a 404 or a blocked host will not change by waiting.
    """

    BASE_DELAY = timedelta(minutes=5)
    MAX_DELAY = timedelta(hours=6)
    MAX_ATTEMPTS = 6

    source = models.ForeignKey("Source", on_delete=models.PROTECT, related_name="fetch_retries")
    url = models.URLField(max_length=2048)
    attempts = models.PositiveSmallIntegerField(default=1)
    next_at = models.DateTimeField()
    error_class = models.CharField(max_length=16, blank=True, choices=ERROR_CLASS_CHOICES)
    gave_up = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "url"], name="unique_fetch_retry"),
        ]
        indexes = [models.Index(fields=["gave_up", "next_at"])]

    def __str__(self):
        return f"{self.source_id}: {self.url[:80]} (attempt {self.attempts})"

    @classmethod
    def schedule(cls, source, url: str, exc: BaseException) -> None:
        """Queue a failed detail fetch. Never raises: the crawl must not die on its own
        bookkeeping, and a source object from a test or a probe may not be a saved row."""
        if classify_exception(exc) is not Transient or not getattr(source, "pk", None):
            return
        try:
            with transaction.atomic():
                cls.objects.get_or_create(
                    source=source, url=url[:2048],
                    defaults={"next_at": timezone.now() + cls.BASE_DELAY,
                              "error_class": error_class(exc)},
                )
        except Exception:
            logger.warning("could not queue retry for %s", url[:200], exc_info=True)

    def failed(self, exc: BaseException, now) -> str:
        """Back off exponentially, or give up. Returns which one happened."""
        self.attempts += 1
        self.error_class = error_class(exc)
        if classify_exception(exc) is Transient and self.attempts < self.MAX_ATTEMPTS:
            self.next_at = now + min(self.BASE_DELAY * 2 ** (self.attempts - 1), self.MAX_DELAY)
            outcome = "rescheduled"
        else:
            self.gave_up = True
            outcome = "gave_up"
        self.save(update_fields=["attempts", "error_class", "next_at", "gave_up", "updated_at"])
        return outcome


class Strategy(models.TextChoices):
    """How a source is crawled. The value keys `sources.strategies.REGISTRY`."""

    RSS_SABA = "rss_saba", "Saba/Nastooh CMS RSS (Mehr, IRNA, ISNA)"
    RSS_GENERIC = "rss_generic", "Standard RSS or Atom feed"
    LISTING_DETAIL = "listing_detail", "Listing page -> detail page"
    LISTING_RELAY = "listing_relay", "Listing page -> interstitial -> real article"


class HealthStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    HEALTHY = "healthy", "Healthy"
    DEGRADED = "degraded", "Degraded"


class Language(models.TextChoices):
    FA = "fa", "Persian"
    EN = "en", "English"


class LicenseMode(models.TextChoices):
    FULL = "full", "Store and show the text"
    # Paywalled or foreign press: keep the facts, show a link, never republish the copy.
    FACTS_LINK_OUT = "facts_link_out", "Facts and a link out"


class SourceRole(models.TextChoices):
    PRIMARY = "primary", "Primary reporter"
    AGGREGATOR = "aggregator", "Aggregator"


AGGREGATOR_GROUP = "aggregator"


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
    public_image_allowed = models.BooleanField(default=False)
    language = models.CharField(max_length=2, choices=Language, default=Language.FA)
    # Ownership or editorial control. Two sources in one group are one voice: IRIB News
    # and YJC repeating a story is not two confirmations.
    independence_group = models.SlugField(max_length=64, blank=True)
    license_mode = models.CharField(max_length=16, choices=LicenseMode, default=LicenseMode.FULL)
    role = models.CharField(max_length=16, choices=SourceRole, default=SourceRole.PRIMARY)
    last_item_published_at = models.DateTimeField(null=True, blank=True)

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

    @property
    def independence_key(self) -> str | None:
        """What a confirmation counts against, or None when this source cannot confirm
        anything: an aggregator only relays what another outlet already said."""
        if self.role == SourceRole.AGGREGATOR or self.independence_group == AGGREGATOR_GROUP:
            return None
        return self.independence_group or self.name

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
