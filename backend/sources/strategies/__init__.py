"""Strategy dispatch.

A strategy is a module exposing `fetch(source, session, *, limit) -> list[RawArticle]` and
optionally `backfill(source, session, *, since_date, seen) -> Iterator[RawArticle]`.

Two properties this table is designed to give:

1. Adding a site that fits an existing shape is a `Source` row, not code. IRNA and ISNA
   were added exactly this way - they run the same CMS as Mehr.
2. Backfill capability is DERIVED from the modules, never hand-listed. A hand-written set
   alongside an if/else dispatch is how the previous version nearly paginated Mehr's
   archive under a different site's name: the set and the dispatch could drift apart, and
   only one of them was tested.
"""

from __future__ import annotations

from types import ModuleType

import requests

from core.errors import Permanent

from ..extraction import RawArticle
from ..models import Strategy
from . import khabarfoori, saba, shahrekhabar

REGISTRY: dict[str, ModuleType] = {
    Strategy.RSS_SABA: saba,
    Strategy.LISTING_DETAIL: khabarfoori,
    Strategy.LISTING_RELAY: shahrekhabar,
}

# Derived, so it cannot disagree with what the modules actually implement.
BACKFILLABLE = frozenset(
    name for name, module in REGISTRY.items() if hasattr(module, "backfill")
)


def _module(strategy: str) -> ModuleType:
    if strategy not in REGISTRY:
        raise Permanent(f"unsupported strategy {strategy!r}")
    return REGISTRY[strategy]


def fetch(source, session: requests.Session, *, limit: int) -> list[RawArticle]:
    """Fetch one source's current articles. Failures propagate so the caller can mark the
    source degraded rather than silently reporting an empty crawl as a healthy one."""
    return _module(source.strategy).fetch(source, session, limit=limit)


def supports_backfill(source) -> bool:
    """A source can backfill only if its strategy implements it AND it has an archive URL.
    Sharing a fetch shape does not mean sharing a history mechanism: Mehr's RSS feed and
    its archive are unrelated endpoints, and Shahrekhabar has no archive at all."""
    return source.strategy in BACKFILLABLE and bool(source.archive_url)


def backfill(source, session: requests.Session, *, since_date: str, seen: set[str]):
    if not supports_backfill(source):
        return iter(())
    return _module(source.strategy).backfill(
        source, session, since_date=since_date, seen=seen
    )
