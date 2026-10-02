"""Articles, their images, and their embeddings.

Two gates sit between "fetched" and "we paid an LLM to read this", and they are separate
fields on purpose because they mean different things and fail differently:

- `quality_flag`   the extractor produced something unusable (no title, no text, a future
                   date). A gate that fires often is a broken parser announcing itself.
- `prefilter_reason` the article is fine, we simply chose not to pay for it - the source's
                   own taxonomy said sports or provincial news. The article is still stored
                   in full, so the decision is auditable and reversible.

Neither is a deletion. Everything fetched is kept; only spending is withheld.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from pgvector.django import HnswIndex, VectorField


class UrlStatus(models.TextChoices):
    LIVE = "live", "Live"
    GONE = "gone", "Permanently gone (404/410)"
    DROPPED = "dropped", "Dropped from the listing"


class ExtractionTier(models.TextChoices):
    """How the body was obtained, best first.

    A source drifting DOWN this ladder is the early warning that a redesign is coming -
    which is why the tier is stored rather than just used and discarded.
    """

    JSONLD = "jsonld", "JSON-LD articleBody"
    OG = "og", "OpenGraph metadata"
    CSS = "css", "CSS selector"
    FEED = "feed", "Feed entry only"
    LISTING = "listing", "Listing row only"


class ArticleQuerySet(models.QuerySet):
    def canonical(self):
        """The stories. Duplicates point at their canonical copy and drop out here."""
        return self.filter(duplicate_of__isnull=True)

    def eligible_for_inference(self):
        return self.canonical().filter(
            quality_flag="", prefilter_reason="", url_status=UrlStatus.LIVE
        )

    def in_window(self, days: int):
        from datetime import timedelta

        from django.utils import timezone

        return self.filter(fetched_at__gte=timezone.now() - timedelta(days=max(days, 1)))


class Article(models.Model):
    # 2048, not 1000. Khabarfoori percent-encodes Persian slugs, which triples their byte
    # length: measured over one listing page the median URL is 367 characters and the
    # longest is 1,090. A 1,000-character column silently held until a long headline
    # appeared, then failed the entire source's crawl.
    url = models.URLField(max_length=2048, unique=True)
    source = models.ForeignKey("sources.Source", on_delete=models.PROTECT, related_name="articles")
    # The outlet credited by the page. Khabarfoori is an aggregator, so this is often a
    # different agency; keeping both separate is what makes cross-source dedup possible.
    original_outlet = models.CharField(max_length=255, blank=True)

    original_title = models.TextField()
    lead = models.TextField(blank=True)
    content = models.TextField(blank=True)
    content_hash = models.CharField(max_length=32, db_index=True)

    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Jalali is stored, not derived on read: the workbook groups by Jalali day and window
    # gap-detection queries it directly, so it needs an index of its own.
    published_at_jalali = models.CharField(max_length=10, blank=True, db_index=True)
    published_time = models.CharField(max_length=5, blank=True)
    date_uncertain = models.BooleanField(default=False)

    # The source's OWN taxonomy slug (Saba CMS `<category domain="gilan">`). Free signal we
    # previously discarded, and the input to the cost prefilter.
    native_category = models.CharField(max_length=64, blank=True, db_index=True)
    keywords = ArrayField(models.CharField(max_length=64), default=list, blank=True)

    extraction_tier = models.CharField(
        max_length=16, choices=ExtractionTier, default=ExtractionTier.CSS
    )
    quality_flag = models.CharField(max_length=64, blank=True, db_index=True)
    prefilter_reason = models.CharField(max_length=64, blank=True, db_index=True)

    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates"
    )
    duplicate_score = models.FloatField(null=True, blank=True)
    duplicate_reason = models.CharField(max_length=32, blank=True)

    fetched_at = models.DateTimeField(db_index=True)
    first_seen_run = models.CharField(max_length=64, blank=True)
    last_seen_run = models.CharField(max_length=64, blank=True)
    url_status = models.CharField(
        max_length=16, choices=UrlStatus, default=UrlStatus.LIVE, db_index=True
    )
    gone_at = models.DateTimeField(null=True, blank=True)
    gone_http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ArticleQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-id"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["source", "created_at"]),
            models.Index(fields=["source", "published_at"]),
            models.Index(fields=["duplicate_of"]),
            models.Index(fields=["original_outlet"]),
        ]

    def __str__(self) -> str:
        return self.original_title[:80]


class NewsEvent(models.Model):
    """A reader-facing story. Articles remain the evidence and retain their own provenance."""

    class Status(models.TextChoices):
        DEVELOPING = "developing", "Developing"
        ASSESSED = "assessed", "Assessed"
        CORRECTED = "corrected", "Corrected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class Evidence(models.TextChoices):
        """How independently the occurrence is reported; see core.events.evidence_level."""

        SINGLE = "single", "One source group"
        MULTI = "multi", "Several independent source groups"
        OFFICIAL = "official", "Reported by an official source"
        DISPUTED = "disputed", "Sources disagree"

    primary_article = models.OneToOneField(
        Article, on_delete=models.PROTECT, related_name="led_event"
    )
    articles = models.ManyToManyField(Article, related_name="news_events", blank=True)
    event_time = models.DateTimeField(db_index=True)
    first_seen_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.DEVELOPING)
    evidence_level = models.CharField(max_length=16, choices=Evidence, default=Evidence.SINGLE)
    category = models.CharField(max_length=32, blank=True, db_index=True)
    iran_score = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    global_score = models.PositiveSmallIntegerField(null=True, blank=True)
    assessment_confidence = models.FloatField(null=True, blank=True)
    title_fa = models.TextField(blank=True)
    title_en = models.TextField(blank=True)
    brief_fa = models.TextField(blank=True)
    brief_en = models.TextField(blank=True)
    channels_fa = models.TextField(blank=True)
    channels_en = models.TextField(blank=True)
    uncertainty_fa = models.TextField(blank=True)
    uncertainty_en = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["-event_time", "-id"])]

    def __str__(self) -> str:
        return f"event {self.pk}: {self.primary_article.original_title[:60]}"


class EventAssessment(models.Model):
    """Append-only Jev decisions; an event's current fields are its read projection."""

    event = models.ForeignKey(NewsEvent, on_delete=models.CASCADE, related_name="assessments")
    model = models.CharField(max_length=80)
    evidence_hash = models.CharField(max_length=64, db_index=True)
    category = models.CharField(max_length=32)
    iran_score = models.PositiveSmallIntegerField()
    global_score = models.PositiveSmallIntegerField()
    asset_scores = models.JSONField(default=dict)
    confidence = models.FloatField()
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Jev assessment for event {self.event_id}"


class EventRevision(models.Model):
    """Reader copy replaced after source evidence changes."""

    event = models.ForeignKey(NewsEvent, on_delete=models.CASCADE, related_name="revisions")
    reason = models.CharField(max_length=32)
    title_fa = models.TextField(blank=True)
    title_en = models.TextField(blank=True)
    brief_fa = models.TextField(blank=True)
    brief_en = models.TextField(blank=True)
    channels_fa = models.TextField(blank=True)
    channels_en = models.TextField(blank=True)
    uncertainty_fa = models.TextField(blank=True)
    uncertainty_en = models.TextField(blank=True)
    observed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"reader revision of event {self.event_id}"


class EventReview(models.Model):
    """Human labels for Jev calibration; the published event remains independent."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        REVIEWED = "reviewed", "Reviewed"

    event = models.OneToOneField(NewsEvent, on_delete=models.CASCADE, related_name="review")
    reason = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    reviewed_category = models.CharField(max_length=32, blank=True)
    reviewed_iran_score = models.PositiveSmallIntegerField(null=True, blank=True)
    reviewed_global_score = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    # A skipped card stays pending but drops behind unskipped ones, so one hard case cannot
    # head every review session.
    skipped_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"review for event {self.event_id}: {self.status}"


class GroupingDecision(models.Model):
    """A staff ruling on whether one article reports the same occurrence as one event.

    `not_same` binds automatic grouping: neither dedup attachment nor a Jev merge puts the
    article back into that event (core.events). The rows double as labelled grouping
    examples for evaluation.
    """

    class Decision(models.TextChoices):
        NOT_SAME = "not_same", "Not the same occurrence"
        SAME = "same", "Same occurrence"

    article = models.ForeignKey(
        Article, on_delete=models.CASCADE, related_name="grouping_decisions"
    )
    event = models.ForeignKey(
        NewsEvent, on_delete=models.CASCADE, related_name="grouping_decisions"
    )
    decision = models.CharField(max_length=16, choices=Decision)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    decided_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["article", "event"], name="one_grouping_decision")
        ]

    def __str__(self) -> str:
        return f"article {self.article_id} {self.decision} event {self.event_id}"


class WatchItem(models.Model):
    """Curated bilingual vocabulary an event can be tagged with: an asset, actor or theme.

    Seeded from articles/fixtures/watch_items.yaml by `seed_watch_items`. Rows are disabled
    rather than deleted so existing tags keep their meaning.
    """

    class Kind(models.TextChoices):
        ASSET = "asset", "Asset"
        ACTOR = "actor", "Actor"
        THEME = "theme", "Theme"

    slug = models.SlugField(max_length=64, unique=True)
    kind = models.CharField(max_length=8, choices=Kind)
    name_fa = models.CharField(max_length=128)
    name_en = models.CharField(max_length=128)
    aliases = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.slug


class EventWatchItem(models.Model):
    """One Jev tag: this event is substantively about this watch item."""

    event = models.ForeignKey(NewsEvent, on_delete=models.CASCADE, related_name="watch_links")
    item = models.ForeignKey(WatchItem, on_delete=models.CASCADE, related_name="event_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "item"], name="one_tag_per_event_item")
        ]

    def __str__(self) -> str:
        return f"event {self.event_id} tagged {self.item_id}"


class AlertSubscription(models.Model):
    """An opted-in browser endpoint; credentials stay server-side."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    endpoint = models.URLField(max_length=2048, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    iran = models.BooleanField(default=True)
    global_events = models.BooleanField(default=False)
    asset_classes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"browser alert subscription {self.pk}"


class EventAlert(models.Model):
    event = models.ForeignKey(NewsEvent, on_delete=models.CASCADE)
    subscription = models.ForeignKey(AlertSubscription, on_delete=models.CASCADE)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "subscription"],
                name="one_alert_per_event_subscription",
            )
        ]

    def __str__(self) -> str:
        return f"alert {self.event_id} to {self.subscription_id}"


class ArticleRevision(models.Model):
    """The content observed before an upstream correction or removal."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="revisions")
    title = models.TextField()
    lead = models.TextField(blank=True)
    content = models.TextField(blank=True)
    content_hash = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    observed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"revision of article {self.article_id} at {self.observed_at}"


class ImageStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    STORED = "stored", "Stored"
    FAILED = "failed", "Failed"
    GONE = "gone", "Permanently gone (404/410)"
    ABSENT = "absent", "No image published"


class ArticleImage(models.Model):
    """The headline image, downloaded and served from our own domain.

    Downloaded rather than hotlinked for three reasons that all bite in production: the
    Iranian CDNs are slow or unreachable from a visitor's browser, they delete images, and
    hotlinking would force a per-CDN exception into the edge Content-Security-Policy.
    """

    article = models.OneToOneField(Article, on_delete=models.CASCADE, related_name="image")
    source_url = models.URLField(max_length=2048, blank=True)
    file = models.ImageField(upload_to="articles/%Y/%m/", blank=True)
    thumbnail = models.ImageField(upload_to="articles/%Y/%m/thumbs/", blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=ImageStatus, default=ImageStatus.PENDING)
    error = models.TextField(blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"image for article {self.article_id} ({self.status})"


class ArticleEmbedding(models.Model):
    """Semantic vector over title+lead, for retrieving similar PAST articles as context.

    Keyed by (article, model) rather than overwritten: changing the embedding model is a
    new row, so a retrieval experiment can be compared against the old one instead of
    destroying it. Dimensionality is per-model, so it is stored alongside.
    """

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="embeddings")
    model = models.CharField(max_length=64)
    dimensions = models.PositiveSmallIntegerField()
    vector = VectorField(dimensions=1536)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["article", "model"], name="unique_article_embedding"),
        ]
        indexes = [
            # Cosine, because the embeddings are normalised and magnitude carries no
            # meaning here - only direction does.
            HnswIndex(
                name="article_embedding_hnsw",
                fields=["vector"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.model} embedding for article {self.article_id}"
