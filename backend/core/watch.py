"""Watch-item tagging: a cheap alias shortlist, then Jev picks from it.

Asking Jev one question per vocabulary item would be ~150 questions per event. Instead the
text is matched against every item's names and aliases (folded Persian, word-start
boundary, optional plural/ezafe suffix), and only the best few matches become questions.
An item no alias mentions is never asked about: recall is bounded by the fixture, which is
the trade for a fixed, small cost per event.
"""

from __future__ import annotations

import re
from collections import Counter

from core.text import title_key

SHORTLIST_SIZE = 8
MAX_TAGS = 5
# Bare word plus the endings that attach without a space: English plural, Persian plural
# (ZWNJ folds to a space, so the spaced form is already a whole word) and ezafe.
_SUFFIX = r"(?:s|es|ها|های|ی|ای)?"


def _pattern(aliases: dict[str, str]) -> re.Pattern:
    alternatives = "|".join(re.escape(key) for key in sorted(aliases, key=len, reverse=True))
    return re.compile(rf"(?<!\w)({alternatives}){_SUFFIX}(?!\w)")


def shortlist(text: str, items, limit: int = SHORTLIST_SIZE) -> dict[str, str]:
    """{slug: "English name (Persian name)"} for the items the text mentions most.

    `items` are WatchItem-like rows with slug, name_en, name_fa and aliases.
    """
    labels, aliases = {}, {}
    for item in items:
        labels[item.slug] = f"{item.name_en} ({item.name_fa})"
        for alias in (item.name_en, item.name_fa, *item.aliases):
            key = title_key(alias)
            if key:
                aliases.setdefault(key, item.slug)
    if not aliases:
        return {}
    hits = Counter(aliases[m.group(1)] for m in _pattern(aliases).finditer(title_key(text)))
    return {slug: labels[slug] for slug, _ in hits.most_common(limit)}


def tag_event(event, slugs) -> None:
    """Add Jev's tags to an event. Tags accumulate: a merge or reassessment never drops one."""
    from articles.models import EventWatchItem, WatchItem

    for item in WatchItem.objects.filter(slug__in=list(slugs)[:MAX_TAGS]):
        EventWatchItem.objects.get_or_create(event=event, item=item)
