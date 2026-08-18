"""Source discovery and extraction.

Every source ends at RawArticle. Site-specific code must not leak past this boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterator
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


def _body(root: Any, data: dict[str, Any], selector: str, *, min_length: int = 0) -> tuple[str, str]:
    """Article body, preferring the published contract over the page's markup.

    Returns (text, tier) so callers can record how the body was obtained. JSON-LD
    articleBody beat the CSS selector on every khabarfoori article measured - the
    selector only reads <p>, so headings, list items and blockquotes were being
    dropped, losing 5-10% of the text. CSS remains the fallback for pages without
    JSON-LD, and a redesign that breaks the selector now shows up as a tier change
    rather than as silently truncated articles.

    `root` may be None (e.g. a generic page with no matching container), in which case
    the CSS body is empty and JSON-LD alone decides the tier.
    """
    published_body = normalize.clean(data.get("articleBody") or "")
    css_body = "\n".join(
        text for p in (root.select(selector) if root else []) if (text := _text(p)) and len(text) > min_length
    )
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


def parse_mehr_archive_listing(html: str, base_url: str) -> list[str]:
    """Mehr's paginated archive index (distinct from its RSS feed, which has no history)."""
    soup = BeautifulSoup(html, "html.parser")
    urls = [
        urljoin(base_url, link["href"])
        for link in soup.select("li.news div.desc h3 a[href]")
    ]
    return list(dict.fromkeys(urls))


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
    container = soup.select_one("article") or soup.select_one(".item-body") or soup.body
    content, tier = _body(container, data, "p", min_length=20)
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


# Historical pagination for the rolling-window backfill. Distinct from _STRATEGIES:
# not every source that shares a *fetch* shape also has a *history* mechanism - Mehr's
# RSS feed and its archive endpoint are unrelated URLs. Keyed by source name because the
# techniques below are genuinely source-specific, not a shape other sources could share.
# Shahrekhabar has no entry: no archive/date endpoint exists for it, so backfill.py skips
# it and the dashboard shows it as capped, rather than the code silently pretending.
# A safety ceiling against a runaway loop, not a target depth - the real stop conditions
# are since_date and the stale-page counter below. 500 matches the legacy pipeline's own
# HARD_MAX_PAGES, which served the same role there. Each page costs 1 listing fetch plus
# 1 detail fetch per new article, so this can still be slow on a wide window against a
# high-volume source; that cost is the tradeoff for actually reaching the window's floor
# instead of stopping short of it.
_MAX_BACKFILL_PAGES = 500
_STALE_PAGE_LIMIT = 2  # consecutive pages with zero new URLs before giving up
_MEHR_ARCHIVE_URL = "https://www.mehrnews.com/archive"
# Mehr's own topic ids; fixed by their site, not something a deployment would edit.
_MEHR_ARCHIVE_CATEGORIES = {"economics": 25, "politics": 7, "society": 6}


def _paginate_backfill(
    session: requests.Session,
    *,
    page_url: Callable[[int], str],
    parse_listing: Callable[[str, str], list[str]],
    listing_base_url: str,
    parse_article: Callable[[str, str], RawArticle],
    since_date: str,
    seen: set[str],
) -> Iterator[RawArticle]:
    """Shared pagination shape: listing page -> new URLs -> detail fetch, until a stale
    run of pages or a URL published before `since_date` is reached. `seen` is mutated in
    place so callers can share dedup state across an outer loop (e.g. Mehr's categories).
    """
    stale = 0
    for page in range(1, _MAX_BACKFILL_PAGES + 1):
        try:
            response = session.get(page_url(page), headers=USER_AGENT, timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            break
        new_urls = [u for u in parse_listing(response.text, listing_base_url) if u not in seen]
        if not new_urls:
            stale += 1
            if stale >= _STALE_PAGE_LIMIT:
                break
            continue
        stale = 0
        reached_since = False
        for url in new_urls:
            seen.add(url)
            try:
                detail = session.get(url, headers=USER_AGENT, timeout=20)
                detail.raise_for_status()
            except requests.RequestException:
                continue
            article = parse_article(detail.text, url)
            yield article
            if article.published_at and article.published_at < since_date:
                reached_since = True
        if reached_since:
            break


def _fetch_backfill_khabarfoori(
    spec: SourceSpec, session: requests.Session, *, since_date: str, known_urls: set[str]
) -> Iterator[RawArticle]:
    yield from _paginate_backfill(
        session,
        page_url=lambda page: spec.url if page == 1 else f"{spec.url}/?page={page}",
        parse_listing=parse_khabarfoori_listing,
        listing_base_url=spec.url,
        parse_article=parse_khabarfoori_article,
        since_date=since_date,
        seen=set(known_urls),
    )


def _fetch_backfill_mehr(
    spec: SourceSpec, session: requests.Session, *, since_date: str, known_urls: set[str]
) -> Iterator[RawArticle]:
    seen = set(known_urls)
    for tp in _MEHR_ARCHIVE_CATEGORIES.values():
        yield from _paginate_backfill(
            session,
            page_url=lambda page, tp=tp: f"{_MEHR_ARCHIVE_URL}?tp={tp}&pi={page}",
            parse_listing=parse_mehr_archive_listing,
            listing_base_url=_MEHR_ARCHIVE_URL,
            parse_article=lambda text, url: parse_generic_article(text, "mehr", url, "مهر"),
            since_date=since_date,
            seen=seen,
        )


_BACKFILL_STRATEGIES: dict[str, Callable[..., Iterator[RawArticle]]] = {
    "khabarfoori": _fetch_backfill_khabarfoori,
    "mehr": _fetch_backfill_mehr,
}


def backfill_fetch(
    spec: SourceSpec, session: requests.Session | None = None, *, since_date: str, known_urls: set[str]
) -> Iterator[RawArticle]:
    """Paginate a source as far back as `since_date` (a 'YYYY-MM-DD' Gregorian floor).

    Only sources with a real history mechanism are registered; others yield nothing.
    """
    handler = _BACKFILL_STRATEGIES.get(spec.name)
    if handler is None:
        return
    session = session or requests.Session()
    yield from handler(spec, session, since_date=since_date, known_urls=known_urls)


def fetch(spec: SourceSpec, session: requests.Session | None = None, *, limit: int = 25) -> list[RawArticle]:
    """Fetch one source. Network failures propagate so the caller can update source health."""
    session = session or requests.Session()
    handler = _STRATEGIES.get(spec.strategy)
    if handler is None:
        raise ValueError(f"unsupported strategy {spec.strategy!r}")
    response = session.get(spec.url, headers=USER_AGENT, timeout=20)
    response.raise_for_status()
    return handler(spec, session, response, limit)
