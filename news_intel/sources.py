"""Source discovery and extraction.

Every source ends at RawArticle. Site-specific code must not leak past this boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from .core import normalize


@dataclass(frozen=True)
class SourceSpec:
    name: str
    tier: int
    strategy: str
    url: str
    enabled: bool = True
    # Lower wins when the same story arrives from several sources. Ranks by how complete
    # that source's copy is: Khabarfoori carries full bodies, Shahrekhabar listings often
    # carry none. See dedupe._better_canonical.
    priority: int = 50


@dataclass(frozen=True)
class RawArticle:
    source: str
    url: str
    title: str
    lead: str = ""
    content: str = ""
    original_outlet: str | None = None
    published_at: str | None = None
    date_uncertain: bool = False
    # How the body was obtained: jsonld > og > css > listing. A source drifting down
    # this ladder is the early warning that a redesign is coming.
    extraction_tier: str = "css"

    @property
    def content_hash(self) -> str:
        return normalize.content_hash(self.title, self.lead, self.content)


USER_AGENT = {"User-Agent": "news-intel/1.0 (+local research pipeline)"}


def load_specs(directory: Path) -> dict[str, SourceSpec]:
    specs: dict[str, SourceSpec] = {}
    for path in sorted(directory.glob("*.yaml")):
        # Source files intentionally contain only scalar key/value pairs. Avoid making
        # startup depend on a YAML parser for this tiny, human-editable registry.
        raw = {
            key.strip(): value.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if ":" in line and not line.lstrip().startswith("#")
            for key, _, value in [line.partition(":")]
        }
        spec = SourceSpec(
            name=str(raw["name"]),
            tier=int(raw["tier"]),
            strategy=str(raw["strategy"]),
            url=str(raw["url"]),
            enabled=raw.get("enabled", "true").lower() not in {"false", "0", "no"},
            priority=int(raw.get("priority", 50)),
        )
        specs[spec.name] = spec
    return specs


def register(conn, specs: dict[str, SourceSpec]) -> None:
    """Persist the registry so dedup and the dashboard can read source metadata."""
    for spec in specs.values():
        conn.execute(
            "INSERT INTO sources(name, tier, config_path, priority, enabled)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET tier=excluded.tier,"
            " priority=excluded.priority, enabled=excluded.enabled",
            (spec.name, spec.tier, f"config/sources/{spec.name}.yaml",
             spec.priority, int(spec.enabled)),
        )


def _text(node: Any) -> str:
    return normalize.clean(node.get_text(" ", strip=True) if node else "")


def _json_ld(soup: BeautifulSoup) -> dict[str, Any]:
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


def parse_khabarfoori_listing(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = [
        urljoin(base_url, link["href"])
        for link in soup.select("ul.box.container h2.title a[href]")
    ]
    return list(dict.fromkeys(urls))


def _body(soup: BeautifulSoup, data: dict[str, Any], selector: str) -> tuple[str, str]:
    """Article body, preferring the published contract over the page's markup.

    Returns (text, tier) so callers can record how the body was obtained. JSON-LD
    articleBody beat the CSS selector on every khabarfoori article measured - the
    selector only reads <p>, so headings, list items and blockquotes were being
    dropped, losing 5-10% of the text. CSS remains the fallback for pages without
    JSON-LD, and a redesign that breaks the selector now shows up as a tier change
    rather than as silently truncated articles.
    """
    published_body = normalize.clean(data.get("articleBody") or "")
    css_body = "\n".join(_text(p) for p in soup.select(selector) if _text(p))
    if len(published_body) >= len(css_body):
        return published_body, "jsonld"
    return css_body, "css"


def parse_khabarfoori_article(html: str, url: str) -> RawArticle:
    soup = BeautifulSoup(html, "html.parser")
    data = _json_ld(soup)
    time = soup.select_one("span.news_time time")
    source = soup.select_one("div.source_news .source_title + span")
    content, tier = _body(soup, data, "#main_ck_editor p")
    published = normalize.clean(data.get("datePublished") or (time or {}).get("datetime", ""))
    return RawArticle(
        source="khabarfoori",
        url=url,
        title=normalize.clean(data.get("headline") or _text(soup.select_one("h1.title"))),
        lead=normalize.clean(data.get("description") or _text(soup.select_one("p.lead"))),
        content=content,
        original_outlet=_text(source) or None,
        published_at=published or None,
        date_uncertain=not bool(published),
        extraction_tier=tier,
    )


def parse_mehr_feed(xml: str) -> list[RawArticle]:
    root = ElementTree.fromstring(xml)
    articles: list[RawArticle] = []
    for item in root.findall(".//item"):
        value = lambda name: normalize.clean(item.findtext(name, default=""))
        published = value("pubDate")
        try:
            published = parsedate_to_datetime(published).isoformat()
        except (TypeError, ValueError):
            published = ""
        articles.append(
            RawArticle(
                source="mehr",
                url=value("link"),
                title=value("title"),
                lead=value("description"),
                content=value("description"),
                original_outlet="مهر",
                published_at=published or None,
                date_uncertain=not bool(published),
            )
        )
    return [article for article in articles if article.url and article.title]


def parse_shahrekhabar_listing(html: str, base_url: str) -> list[RawArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[RawArticle] = []
    for item in soup.select("ul.news-list-items > li"):
        link = item.select_one("a[href]")
        if not link:
            continue
        title = _text(link)
        if not title:
            continue
        articles.append(
            RawArticle(
                source="shahrekhabar",
                url=urljoin(base_url, link["href"]),
                title=title,
                original_outlet=_text(item.select_one(".refrence.minw88")) or None,
                date_uncertain=True,
            )
        )
    return list({article.url: article for article in articles}.values())


def parse_generic_article(html: str, source: str, url: str, outlet: str | None = None) -> RawArticle:
    soup = BeautifulSoup(html, "html.parser")
    data = _json_ld(soup)
    published_body = normalize.clean(data.get("articleBody") or "")
    container = soup.select_one("article") or soup.select_one(".item-body") or soup.body
    css_body = (
        "\n".join(_text(p) for p in container.select("p") if len(_text(p)) > 20)
        if container
        else ""
    )
    content, tier = (
        (published_body, "jsonld") if len(published_body) >= len(css_body) else (css_body, "css")
    )
    published = normalize.clean(data.get("datePublished"))
    return RawArticle(
        source=source,
        url=url,
        title=normalize.clean(data.get("headline") or _text(soup.select_one("h1"))),
        lead=normalize.clean(data.get("description") or _text(soup.select_one(".lead, .summary"))),
        content=content,
        original_outlet=outlet,
        published_at=published or None,
        date_uncertain=not bool(published),
        extraction_tier=tier,
    )


def shahrekhabar_target(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    iframe = soup.select_one("iframe[src]")
    if iframe:
        return urljoin(page_url, iframe["src"])
    refresh = soup.select_one('meta[http-equiv="refresh" i][content*="url=" i]')
    if refresh:
        return urljoin(page_url, refresh["content"].split("url=", 1)[-1].strip())
    return page_url


# Registry of fetch strategies, keyed by SourceSpec.strategy. Adding a source that fits
# an existing shape (another RSS feed, another listing-page-then-detail-page site) is a
# new config/sources/*.yaml file only. A genuinely new page shape needs one function
# registered here - fetch() itself never changes.
_STRATEGIES: dict[str, Callable[[SourceSpec, requests.Session, "requests.Response", int], list[RawArticle]]] = {}


def strategy(name: str):
    def register(fn):
        _STRATEGIES[name] = fn
        return fn
    return register


@strategy("rss")
def _fetch_rss(spec: SourceSpec, session: requests.Session, response, limit: int) -> list[RawArticle]:
    # The feed carries only a short description. Without fetching the page, every
    # article from this source reached the classifier with ~150 characters while
    # other sources supplied 1,300+, so the same model was judging them on far less
    # evidence. Fall back to the feed entry when the page cannot be fetched.
    articles = []
    for entry in parse_mehr_feed(response.text)[:limit]:
        try:
            page = session.get(entry.url, headers=USER_AGENT, timeout=20)
            page.raise_for_status()
        except requests.RequestException:
            articles.append(replace(entry, extraction_tier="feed"))
            continue
        full = parse_generic_article(page.text, entry.source, entry.url, entry.original_outlet)
        articles.append(
            replace(
                entry,
                content=full.content or entry.content,
                lead=entry.lead or full.lead,
                title=entry.title or full.title,
                published_at=entry.published_at or full.published_at,
                extraction_tier=full.extraction_tier if full.content else "feed",
            )
        )
    return articles


@strategy("listing_detail")
def _fetch_listing_detail(spec: SourceSpec, session: requests.Session, response, limit: int) -> list[RawArticle]:
    urls = parse_khabarfoori_listing(response.text, spec.url)[:limit]
    articles = []
    for url in urls:
        detail = session.get(url, headers=USER_AGENT, timeout=20)
        detail.raise_for_status()
        articles.append(parse_khabarfoori_article(detail.text, url))
    return articles


@strategy("listing_relay")
def _fetch_listing_relay(spec: SourceSpec, session: requests.Session, response, limit: int) -> list[RawArticle]:
    articles = []
    for listed in parse_shahrekhabar_listing(response.text, spec.url):
        try:
            relay = session.get(listed.url, headers=USER_AGENT, timeout=20)
            relay.raise_for_status()
            target = shahrekhabar_target(relay.text, listed.url)
            detail = relay if target == listed.url else session.get(target, headers=USER_AGENT, timeout=20)
            detail.raise_for_status()
        except requests.RequestException:
            continue
        extracted = parse_generic_article(detail.text, listed.source, target, listed.original_outlet)
        articles.append(replace(
            extracted,
            title=extracted.title or listed.title,
            lead=extracted.lead or listed.lead,
            original_outlet=extracted.original_outlet or listed.original_outlet,
        ))
        if len(articles) >= limit:
            break
    return articles


def fetch(spec: SourceSpec, session: requests.Session | None = None, *, limit: int = 25) -> list[RawArticle]:
    """Fetch one source. Network failures propagate so the caller can update source health."""
    session = session or requests.Session()
    handler = _STRATEGIES.get(spec.strategy)
    if handler is None:
        raise ValueError(f"unsupported strategy {spec.strategy!r}")
    response = session.get(spec.url, headers=USER_AGENT, timeout=20)
    response.raise_for_status()
    return handler(spec, session, response, limit)
