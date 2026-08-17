#!/usr/bin/env python3
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OLD_DB = BASE_DIR / "خبر فوری" / "JSON Files" / "news_database.json"
NEW_DB = BASE_DIR / "TEST_OUTPUT" / "JSON Files" / "news_database.json"
OUTPUT_ALL = BASE_DIR / "pipeline_comparison_all.txt"
OUTPUT_SAME = BASE_DIR / "pipeline_comparison_same.txt"
OUTPUT_DIFF = BASE_DIR / "pipeline_comparison_different.txt"

old_db = json.load(open(OLD_DB, encoding='utf-8'))
new_db = json.load(open(NEW_DB, encoding='utf-8'))
common_urls = set(old_db.keys()) & set(new_db.keys())

def format_article(old, new):
    lines = []
    old_cat = old.get('classification_category', 'unknown')
    new_cat = new.get('classification_category', 'unknown')

    lines.append("OLD NEWS:")
    lines.append(f"{old.get('original_title', '')}\n")
    if old_cat == 'other':
        lines.append(f"{old.get('lead', '')}\n")
    else:
        lines.append(f"{old.get('one_line_description', '')}\n")
    lines.append(f"{old.get('source', '')} | {old.get('published_at_persian', '')} | {old.get('published_time', '')}\n")

    lines.append("NEW NEWS:")
    lines.append(f"{new.get('original_title', '')}\n")
    if new_cat == 'other':
        lines.append(f"{new.get('lead', '')}\n")
    else:
        lines.append(f"{new.get('one_line_description', '')}\n")
    lines.append(f"{new.get('source', '')} | {new.get('published_at_persian', '')} | {new.get('published_time', '')}\n")

    lines.append(f"OLD CATEGORY -> {old_cat}")
    lines.append(f"NEW CATEGORY -> {new_cat}\n")

    old_notified = "NOTIFIED" if old.get('notified') else "NOT NOTIFIED"
    new_notified = "NOTIFIED" if new.get('notified') else "NOT NOTIFIED"
    lines.append(f"OLD NOTIFY STATUS -> {old_notified}")
    lines.append(f"NEW NOTIFY STATUS -> {new_notified}")
    lines.append("\n" + "-" * 80 + "\n")
    return "\n".join(lines)

same_articles = []
diff_articles = []

for url in common_urls:
    old = old_db[url]
    new = new_db[url]

    if (old.get('published_at_persian') != new.get('published_at_persian') or
        old.get('source') != new.get('source') or
        old.get('published_time') != new.get('published_time')):
        continue

    old_cat = old.get('classification_category', 'unknown')
    new_cat = new.get('classification_category', 'unknown')
    old_notified = old.get('notified', False)
    new_notified = new.get('notified', False)

    if old_cat == new_cat and old_notified == new_notified:
        same_articles.append((old, new))
    else:
        diff_articles.append((old, new))

def sort_key(pair):
    a = pair[0]
    return (a.get('published_at_persian', ''), a.get('published_time', ''))

same_articles.sort(key=sort_key, reverse=True)
diff_articles.sort(key=sort_key, reverse=True)

with open(OUTPUT_ALL, 'w', encoding='utf-8') as f:
    f.write(f"ALL COMMON ARTICLES - {len(same_articles) + len(diff_articles)} Total\n")
    f.write("=" * 80 + "\n\n")
    for old, new in same_articles + diff_articles:
        f.write(format_article(old, new))

with open(OUTPUT_SAME, 'w', encoding='utf-8') as f:
    f.write(f"SAME CLASSIFICATION & EVALUATION - {len(same_articles)} Articles\n")
    f.write("=" * 80 + "\n\n")
    for old, new in same_articles:
        f.write(format_article(old, new))

with open(OUTPUT_DIFF, 'w', encoding='utf-8') as f:
    f.write(f"DIFFERENT CLASSIFICATION OR EVALUATION - {len(diff_articles)} Articles\n")
    f.write("=" * 80 + "\n\n")
    for old, new in diff_articles:
        f.write(format_article(old, new))

print(f"✅ Created 3 comparison files:")
print(f"   All: {len(same_articles) + len(diff_articles)} articles → pipeline_comparison_all.txt")
print(f"   Same: {len(same_articles)} articles → pipeline_comparison_same.txt")
print(f"   Different: {len(diff_articles)} articles → pipeline_comparison_different.txt")
