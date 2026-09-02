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

from django.contrib.postgres.fields import ArrayField
from django.db import models
from pgvector.django import HnswIndex, VectorField

from core.text import content_hash


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
        return self.canonical().filter(quality_flag="", prefilter_reason="")

    def in_window(self, days: int):
        from datetime import timedelta

        from django.utils import timezone

        return self.filter(fetched_at__gte=timezone.now() - timedelta(days=max(days, 1) - 1))


class Article(models.Model):
    url = models.URLField(max_length=1000, unique=True)
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
    first_seen_run = models.CharField(max_length=32, blank=True)
    last_seen_run = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ArticleQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-id"]
        indexes = [
            models.Index(fields=["source", "published_at"]),
            models.Index(fields=["duplicate_of"]),
            models.Index(fields=["original_outlet"]),
        ]

    def __str__(self) -> str:
        return self.original_title[:80]

    def recompute_content_hash(self) -> str:
        self.content_hash = content_hash(self.original_title, self.lead, self.content)
        return self.content_hash

    @property
    def is_canonical(self) -> bool:
        return self.duplicate_of_id is None


class ImageStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    STORED = "stored", "Stored"
    FAILED = "failed", "Failed"
    ABSENT = "absent", "No image published"


class ArticleImage(models.Model):
    """The headline image, downloaded and served from our own domain.

    Downloaded rather than hotlinked for three reasons that all bite in production: the
    Iranian CDNs are slow or unreachable from a visitor's browser, they delete images, and
    hotlinking would force a per-CDN exception into the edge Content-Security-Policy.
    """

    article = models.OneToOneField(Article, on_delete=models.CASCADE, related_name="image")
    source_url = models.URLField(max_length=1000)
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
