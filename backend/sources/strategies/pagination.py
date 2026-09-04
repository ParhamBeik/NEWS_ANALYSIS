"""Archive pagination, shared by every source that has a history endpoint.

The page cap is a runaway guard, not a target depth. The real stop conditions are
`since_date` and the stale-page counter: a listing that returns nothing new twice in a row
is the end of the archive, whatever the pager claims.

Each page costs one listing fetch plus one detail fetch per new article, so a wide window
against a busy source is genuinely slow. That is the price of actually reaching the
window's floor, and it is why backfill runs behind a gap check rather than every cycle.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import requests

from ..extraction import RawArticle, fetch_text

MAX_PAGES = 500  # matches the legacy HARD_MAX_PAGES
STALE_PAGE_LIMIT = 2  # consecutive pages with zero new URLs before giving up


def paginate(
    session: requests.Session,
    *,
    page_url: Callable[[int], str],
    parse_listing: Callable[[str, str], list[str]],
    listing_base_url: str,
    parse_article: Callable[[str, str], RawArticle],
    since_date: str,
    seen: set[str],
) -> Iterator[RawArticle]:
    """listing page -> new URLs -> detail fetch, until a stale run of pages or an article
    published before `since_date`.

    `seen` is mutated so callers can share dedup state across several archive categories.
    """
    stale = 0
    for page in range(1, MAX_PAGES + 1):
        try:
            listing = fetch_text(session, page_url(page))
        except Exception:
            return
        new_urls = [
            url for url in parse_listing(listing, listing_base_url) if url not in seen
        ]
        if not new_urls:
            stale += 1
            if stale >= STALE_PAGE_LIMIT:
                return
            continue
        stale = 0
        reached_floor = False
        for url in new_urls:
            seen.add(url)
            try:
                detail = fetch_text(session, url)
            except Exception:
                continue
            article = parse_article(detail, url)
            yield article
            reached_floor |= bool(article.published_at and article.published_at < since_date)
        if reached_floor:
            return
