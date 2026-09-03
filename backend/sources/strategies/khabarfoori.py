"""Khabarfoori: listing page -> detail page.

Khabarfoori is an aggregator, so `original_outlet` is usually a different agency than the
source that fetched it. Keeping the two separate is what makes cross-source dedup work at
all - the same story arriving from Mehr directly and from Khabarfoori's republication has
to be recognisable as one story.

Diagnosed and fixed here: the listing yields only TEN links per page, so a crawl asking
for 40 articles silently got 10 and the window never filled from this source. The listing
is now paged during the normal cycle, not only during backfill.
"""

from __future__ import annotations

from urllib.parse import urljoin

import requests

from core.text import clean

from ..extraction import (
    RawArticle,
    body_text,
    get,
    image_from,
    json_ld,
    keywords_from,
    node_text,
    soup_of,
)

LISTING_SELECTOR = "ul.box.container h2.title a[href]"
# A listing page holds 10 links. Anything beyond a handful of pages per cycle is a backfill
# job, not a crawl - this cap keeps one slow source from monopolising the crawl worker.
MAX_LISTING_PAGES = 8


def parse_listing(html: str, base_url: str) -> list[str]:
    soup = soup_of(html)
    return list(
        dict.fromkeys(
            urljoin(base_url, link["href"]) for link in soup.select(LISTING_SELECTOR)
        )
    )


def page_url(base_url: str, page: int) -> str:
    return base_url if page == 1 else f"{base_url}/?page={page}"


def parse_article(html: str, url: str, source: str = "khabarfoori") -> RawArticle:
    soup = soup_of(html)
    data = json_ld(soup)
    stamp = soup.select_one("span.news_time time")
    content, tier = body_text(soup, data, "#main_ck_editor p")
    published = clean(data.get("datePublished")) or clean(
        stamp.get("datetime", "") if stamp else ""
    )
    return RawArticle(
        source=source,
        url=url,
        title=clean(data.get("headline")) or node_text(soup.select_one("h1.title")),
        lead=clean(data.get("description")) or node_text(soup.select_one("p.lead")),
        content=content,
        original_outlet=node_text(soup.select_one("div.source_news .source_title + span"))
        or None,
        published_at=published or None,
        date_uncertain=not published,
        extraction_tier=tier,
        keywords=keywords_from(soup, data),
        image_url=image_from(soup, data, url),
    )


def collect_urls(session: requests.Session, base_url: str, *, limit: int) -> list[str]:
    """Walk listing pages until `limit` URLs are gathered or a page adds nothing new."""
    urls: list[str] = []
    seen: set[str] = set()
    for page in range(1, MAX_LISTING_PAGES + 1):
        found = [url for url in parse_listing(get(session, page_url(base_url, page)).text, base_url)
                 if url not in seen]
        if not found:
            break
        seen.update(found)
        urls.extend(found)
        if len(urls) >= limit:
            break
    return urls[:limit]


def fetch(spec, session: requests.Session, *, limit: int) -> list[RawArticle]:
    articles = []
    for url in collect_urls(session, spec.url, limit=limit):
        try:
            articles.append(parse_article(get(session, url).text, url, spec.name))
        except Exception:
            # A single unreachable detail page is not a source failure. The listing already
            # proved the source is alive.
            continue
    return articles


def backfill(spec, session: requests.Session, *, since_date: str, seen: set[str]):
    from .pagination import paginate

    yield from paginate(
        session,
        page_url=lambda page: page_url(spec.archive_url or spec.url, page),
        parse_listing=parse_listing,
        listing_base_url=spec.archive_url or spec.url,
        parse_article=lambda html, url: parse_article(html, url, spec.name),
        since_date=since_date,
        seen=seen,
    )
