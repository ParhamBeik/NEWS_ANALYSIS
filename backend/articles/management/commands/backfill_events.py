"""Create reader events for articles collected before event projection was introduced."""

from django.core.management.base import BaseCommand

from articles.models import Article
from core.events import attach_article


class Command(BaseCommand):
    help = "Idempotently attach stored articles to reader events."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        qs = Article.objects.order_by("id")
        if options["limit"] > 0:
            qs = qs[: options["limit"]]
        count = 0
        for article in qs.iterator(chunk_size=500):
            attach_article(article)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"attached {count} articles to reader events"))
