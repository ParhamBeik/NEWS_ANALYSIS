# Storage policy (decided 2026-10-02)

NewsIntel runs on one 100 GB VPS shared with three other apps, with **no
backups**. Every change that stores data must follow these rules. Read before
adding a field, a volume, a downloader or a cache.

## Rules

1. **One image per article.** `download_image` stores a single 800px WebP in
   `ArticleImage.file`; `thumbnail` stays empty. Card and hero both use it.
   Never store originals or a second size.
2. **The source URL is the record.** `ArticleImage.source_url` is kept for every
   image. If a source is unreachable the row ends FAILED/GONE and the article
   shows no picture; the story is the product.
3. **Text and analysis are the core data.** Article text, classifications and
   embeddings are kept in full.
4. **No backups or second copies** on the VPS, the Mac or external drives,
   until a backup plan is written down and approved.

## Why

The old 1200px JPEG + 400px thumbnail pair cost ~115 KB per article
(~400 MB/day). One 800px WebP is ~35 KB. The disk monitor pauses collectors at
95% use.

## Cleanup

`python manage.py compact_images --dry-run`, then without `--dry-run`,
re-encodes legacy pairs into one WebP, requeues rows whose files are missing,
and deletes unreferenced files under `media/articles/`.
