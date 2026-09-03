"""Shahrekhabar: listing page -> interstitial -> the real article.

Shahrekhabar is an index, not a publisher: its links go to a relay page that either frames
the original article in an iframe or redirects to it with a meta refresh. The article we
actually want lives on the originating outlet's domain, so `original_outlet` matters more
here than for any other source.

Listing rows carry no date, so every article from this source arrives `date_uncertain`
until the detail page supplies one. Dedup handles undated articles through an
ingest-order fallback rather than skipping them, which is what used to happen.

This source has no archive endpoint. It is not backfillable, and /ops reports that
honestly instead of showing a permanent gap it will never close.
"""

from __future__ import annotations

from urllib.parse import urljoin

import requests

from ..extraction import RawArticle, get, node_text, parse_generic_article, soup_of


def parse_listing(html: str, base_url: str) -> list[RawArticle]:
    soup = soup_of(html)
    articles = []
    for item in soup.select("ul.news-list-items > li"):
        link = item.select_one("a[href]")
        if link and (title := node_text(link)):
            articles.append(
                RawArticle(
                    source="shahrekhabar",
                    url=urljoin(base_url, link["href"]),
                    title=title,
                    original_outlet=node_text(item.select_one(".refrence.minw88")) or None,
                    date_uncertain=True,
                    extraction_tier="listing",
                )
            )
    return list({article.url: article for article in articles}.values())


def relay_target(html: str, page_url: str) -> str:
    """Where the interstitial actually points. Falls back to the relay page itself, which
    still parses - some entries are hosted rather than framed."""
    soup = soup_of(html)
    if iframe := soup.select_one("iframe[src]"):
        return urljoin(page_url, iframe["src"])
    if refresh := soup.select_one('meta[http-equiv="refresh" i][content*="url=" i]'):
        return urljoin(page_url, refresh["content"].split("url=", 1)[-1].strip())
    return page_url


def fetch(spec, session: requests.Session, *, limit: int) -> list[RawArticle]:
    articles: list[RawArticle] = []
    for listed in parse_listing(get(session, spec.url).text, spec.url):
        try:
            relay = get(session, listed.url)
            target = relay_target(relay.text, listed.url)
            detail = relay if target == listed.url else get(session, target)
        except Exception:
            continue
        extracted = parse_generic_article(
            detail.text, listed.source, target, listed.original_outlet
        )
        # The listing knows the title and crediting outlet; the detail page knows the body
        # and the date. Neither is complete on its own.
        articles.append(extracted.merged_with(listed))
        if len(articles) >= limit:
            break
    return articles
