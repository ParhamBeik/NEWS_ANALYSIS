"""Shared extraction primitives, and the boundary type every strategy ends at.

Site-specific code must not leak past `RawArticle`. Everything downstream - dedup,
quality gating, inference, the workbook - sees the same shape regardless of whether it
came from an RSS feed, a listing page or a relay interstitial.

`extraction_tier` records HOW the body was obtained, best first. That field is not
decoration: a source drifting down the ladder is the early warning that a redesign is
coming, and it shows up on /ops before anyone notices the workbook getting thinner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings

from core.errors import Transient
from core.text import clean, content_hash


@dataclass(frozen=True)
class RawArticle:
    """What a strategy produces. Storage-agnostic on purpose - it is a parse result, not a
    row, and it exists before any decision about whether to keep it."""

    source: str
    url: str
    title: str
    lead: str = ""
    content: str = ""
    original_outlet: str | None = None
    published_at: str | None = None
    date_uncertain: bool = False
    extraction_tier: str = "css"
    # The source's own taxonomy slug, when it publishes one. Free signal, and the input to
    # the cost prefilter - previously discarded on every fetch.
    native_category: str = ""
    keywords: list[str] = field(default_factory=list)
    image_url: str = ""

    @property
    def content_hash(self) -> str:
        return content_hash(self.title, self.lead, self.content)

    def merged_with(self, other: RawArticle) -> RawArticle:
        """Fill this article's empty fields from `other`. Used when a listing row and a
        detail page each know something the other does not."""
        return replace(
            self,
            title=self.title or other.title,
            lead=self.lead or other.lead,
            content=self.content or other.content,
            original_outlet=self.original_outlet or other.original_outlet,
            published_at=self.published_at or other.published_at,
            native_category=self.native_category or other.native_category,
            keywords=self.keywords or other.keywords,
            image_url=self.image_url or other.image_url,
        )


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": settings.NEWS_USER_AGENT})
    return session


def get(session: requests.Session, url: str) -> requests.Response:
    """One HTTP attempt. Retry belongs to the Celery task, never here - a retry loop at
    both layers compounds into nine requests for one logical fetch."""
    try:
        response = session.get(url, timeout=settings.NEWS_HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise Transient(f"fetch failed: {exc}") from exc
    if response.status_code >= 500 or response.status_code == 429:
        raise Transient(f"retryable HTTP {response.status_code} for {url}")
    response.raise_for_status()
    return response


def soup_of(html: str) -> BeautifulSoup:
    # lxml over html.parser: these pages carry unclosed tags that html.parser silently
    # nests, which moves the article body inside a stray element and empties the selector.
    return BeautifulSoup(html, "lxml")


def node_text(node: Any) -> str:
    return clean(node.get_text(" ", strip=True) if node else "")


def meta_content(soup: BeautifulSoup, *selectors: str) -> str:
    """First non-empty `content` attribute among the given meta selectors."""
    for selector in selectors:
        if (tag := soup.select_one(selector)) and (value := tag.get("content")):
            return clean(value)
    return ""


def json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    """The page's NewsArticle/Article JSON-LD node, or an empty dict.

    Walks `@graph` because several Iranian CMSes nest the article node inside one rather
    than publishing it at the top level.
    """
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(tag.string or tag.get_text())
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                candidates.extend(item["@graph"])
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") in {"NewsArticle", "Article"}:
                return item
    return {}


def body_text(
    root: Any, data: dict[str, Any], selector: str, *, min_length: int = 0
) -> tuple[str, str]:
    """Article body as (text, tier), preferring published JSON-LD over the markup.

    `articleBody` beat the CSS selector on every Khabarfoori article measured - the
    selector only reads <p>, dropping headings, list items and blockquotes, which is 5-10%
    of the text. CSS stays the fallback, so a redesign shows up as a tier change rather
    than as silent truncation. `root` may be None, in which case JSON-LD alone decides.
    """
    published = clean(data.get("articleBody") or "")
    css = "\n".join(
        line
        for element in (root.select(selector) if root else [])
        if (line := node_text(element)) and len(line) > min_length
    )
    return (published, "jsonld") if len(published) >= len(css) else (css, "css")


def image_from(soup: BeautifulSoup, data: dict[str, Any], page_url: str) -> str:
    """Headline image URL: JSON-LD first, then OpenGraph, then Twitter card.

    JSON-LD leads because it names the article's own image; og:image on these sites
    occasionally falls back to the site logo on pages that publish no photo.
    """
    candidate = data.get("image")
    if isinstance(candidate, dict):
        candidate = candidate.get("url")
    elif isinstance(candidate, list) and candidate:
        first = candidate[0]
        candidate = first.get("url") if isinstance(first, dict) else first
    url = clean(candidate if isinstance(candidate, str) else "") or meta_content(
        soup, 'meta[property="og:image"]', 'meta[name="twitter:image"]'
    )
    return urljoin(page_url, url) if url else ""


def keywords_from(soup: BeautifulSoup, data: dict[str, Any], limit: int = 12) -> list[str]:
    """The page's own tags. Khabarfoori publishes these and they were being discarded."""
    raw = data.get("keywords") or meta_content(soup, 'meta[name="keywords"]')
    values = raw if isinstance(raw, list) else str(raw or "").split(",")
    seen: list[str] = []
    for value in values:
        if (tag := clean(value)[:64]) and tag not in seen:
            seen.append(tag)
    return seen[:limit]


def parse_generic_article(
    html: str, source: str, url: str, outlet: str | None = None
) -> RawArticle:
    """Best-effort extraction for any Saba-family or standard article page."""
    soup = soup_of(html)
    data = json_ld(soup)
    container = soup.select_one("article") or soup.select_one(".item-body") or soup.body
    content, tier = body_text(container, data, "p", min_length=20)
    published = clean(data.get("datePublished"))
    return RawArticle(
        source=source,
        url=url,
        title=clean(data.get("headline")) or node_text(soup.select_one("h1")),
        lead=clean(data.get("description"))
        or node_text(soup.select_one(".lead, .summary, .introtext")),
        content=content,
        original_outlet=outlet,
        published_at=published or None,
        date_uncertain=not published,
        extraction_tier=tier,
        keywords=keywords_from(soup, data),
        image_url=image_from(soup, data, url),
    )
