"""Bring stored article images in line with docs/STORAGE-POLICY.md.

- A STORED row keeps ONE file: its display copy (or, if that is gone, its thumbnail)
  re-encoded to the policy's WebP size. The other copy is deleted.
- A STORED row whose files are all missing goes back to PENDING with empty paths, so
  `download_pending_images` fetches it again at the policy size. Unreachable sources then
  end FAILED/GONE like any other image, and the card shows no picture.
- Files under articles/ that no row references are deleted.

    manage.py compact_images --dry-run
    manage.py compact_images
"""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image, UnidentifiedImageError

from articles.models import ArticleImage, ImageStatus
from articles.tasks import IMAGE_MAX, _encode


class Command(BaseCommand):
    help = "Keep one WebP image per article; requeue missing ones; delete unreferenced files."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, dry_run: bool = False, **options):
        counts = {"dry_run": dry_run, "compacted": 0, "already_compact": 0,
                  "requeued": 0, "unreadable": 0, "orphan_files": 0}
        rows = ArticleImage.objects.filter(status=ImageStatus.STORED).order_by("pk")
        for row in rows.iterator(chunk_size=500):
            storage = row.file.storage
            big, thumb = (f.name if f and storage.exists(f.name) else ""
                          for f in (row.file, row.thumbnail))
            if big.endswith(".webp") and not row.thumbnail:
                counts["already_compact"] += 1
                continue
            source = big or thumb
            if not source:
                counts["requeued"] += 1
                if not dry_run:
                    ArticleImage.objects.filter(pk=row.pk).update(
                        file="", thumbnail="", status=ImageStatus.PENDING, error="")
                continue
            counts["compacted"] += 1
            if dry_run:
                continue
            try:
                with storage.open(source) as handle:
                    image = Image.open(handle)
                    image.load()
            except (UnidentifiedImageError, OSError):
                counts["unreadable"] += 1
                ArticleImage.objects.filter(pk=row.pk).update(
                    file="", thumbnail="", status=ImageStatus.PENDING, error="")
                for name in {big, thumb} - {""}:
                    storage.delete(name)
                continue
            row.file.save(f"{row.article_id}.webp", _encode(image, IMAGE_MAX), save=False)
            row.thumbnail = ""
            row.save(update_fields=["file", "thumbnail"])
            for name in {big, thumb} - {"", row.file.name}:
                storage.delete(name)

        referenced = set()
        for file, thumbnail in ArticleImage.objects.values_list("file", "thumbnail").iterator():
            referenced.update(n for n in (file, thumbnail) if n)
        root = os.path.join(settings.MEDIA_ROOT, "articles")
        for directory, _, names in os.walk(root):
            for name in names:
                path = os.path.join(directory, name)
                if os.path.relpath(path, settings.MEDIA_ROOT) not in referenced:
                    counts["orphan_files"] += 1
                    if not dry_run:
                        os.remove(path)
        self.stdout.write(json.dumps(counts))
