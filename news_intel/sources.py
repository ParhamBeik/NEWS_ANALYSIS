"""Source discovery and extraction. Every source ends at RawArticle; site-specific code
must not leak past that boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
import yaml
from bs4 import BeautifulSoup

from . import config, text

USER_AGENT = {"User-Agent": "news-intel/1.0 (+local research pipeline)"}
TIMEOUT = 20


@dataclass(frozen=True)
class SourceSpec:
    name: str
    tier: int
    strategy: str
    url: str
    enabled: bool = True
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
    # How the body was obtained: jsonld > og > css > listing. A source drifting down this
    # ladder is the early warning that a redesign is coming.
    extraction_tier: str = "css"

    @property
    def content_hash(self) -> str:
        return text.content_hash(self.title, self.lead, self.content)


def load_specs(path: Path | None = None) -> dict[str, SourceSpec]:
    document = yaml.safe_load((path or config.SOURCES_PATH).read_text(encoding="utf-8")) or {}
    return {name: SourceSpec(name=name, **entry) for name, entry in document.items()}


def register(conn, specs: dict[str, SourceSpec]) -> None:
    """Persist the registry so dedup and the dashboard can read source metadata."""
    for spec in specs.values():
        conn.execute(
            "INSERT INTO sources(name, tier, config_path, priority, enabled) VALUES(?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET tier=excluded.tier,"
            " priority=excluded.priority, enabled=excluded.enabled",
            (spec.name, spec.tier, "config/sources.yaml", spec.priority, int(spec.enabled)),
        )


# ------------------------------------------------------------------------- extraction


def _text(node: Any) -> str:
    return text.clean(node.get_text(" ", strip=True) if node else "")


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


def _body(root: Any, data: dict[str, Any], selector: str, *, min_length: int = 0) -> tuple[str, str]:
    """Article body as (text, tier), preferring the published JSON-LD over the markup.

    articleBody beat the CSS selector on every khabarfoori article measured - the selector
    only reads <p>, dropping headings, list items and blockquotes (5-10% of the text). CSS
    stays the fallback, so a redesign shows up as a tier change rather than as silent
    truncation. `root` may be None, in which case JSON-LD alone decides.
    """
    published = text.clean(data.get("articleBody") or "")
    css = "\n".join(
        line for p in (root.select(selector) if root else [])
        if (line := _text(p)) and len(line) > min_length
    )
    return (published, "jsonld") if len(published) >= len(css) else (css, "css")


def parse_khabarfoori_listing(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return list(dict.fromkeys(
        urljoin(base_url, link["href"])
        for link in soup.select("ul.box.container h2.title a[href]")
    ))


def parse_khabarfoori_article(html: str, url: str) -> RawArticle:
    soup = BeautifulSoup(html, "html.parser")
    data = _json_ld(soup)
    stamp = soup.select_one("span.news_time time")
    content, tier = _body(soup, data, "#main_ck_editor p")
    published = text.clean(data.get("datePublished") or (stamp or {}).get("datetime", ""))
    return RawArticle(
        source="khabarfoori",
        url=url,
        title=text.clean(data.get("headline") or _text(soup.select_one("h1.title"))),
        lead=text.clean(data.get("description") or _text(soup.select_one("p.lead"))),
        content=content,
        original_outlet=_text(soup.select_one("div.source_news .source_title + span")) or None,
        published_at=published or None,
        date_uncertain=not published,
        extraction_tier=tier,
    )


def parse_mehr_feed(xml: str) -> list[RawArticle]:
    articles = []
    for item in ElementTree.fromstring(xml).findall(".//item"):
        value = lambda name: text.clean(item.findtext(name, default=""))
        try:
            published = parsedate_to_datetime(value("pubDate")).isoformat()
        except (TypeError, ValueError):
            published = ""
        articles.append(RawArticle(
            source="mehr", url=value("link"), title=value("title"),
            lead=value("description"), content=value("description"),
            original_outlet="مهر", published_at=published or None,
            date_uncertain=not published,
        ))
    return [article for article in articles if article.url and article.title]


def parse_mehr_archive_listing(html: str, base_url: str) -> list[str]:
    """Mehr's paginated archive index, distinct from its RSS feed (which has no history)."""
    soup = BeautifulSoup(html, "html.parser")
    return list(dict.fromkeys(
        urljoin(base_url, link["href"]) for link in soup.select("li.news div.desc h3 a[href]")
    ))


def parse_shahrekhabar_listing(html: str, base_url: str) -> list[RawArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    for item in soup.select("ul.news-list-items > li"):
        link = item.select_one("a[href]")
        if link and (title := _text(link)):
            articles.append(RawArticle(
                source="shahrekhabar",
                url=urljoin(base_url, link["href"]),
                title=title,
                original_outlet=_text(item.select_one(".refrence.minw88")) or None,
                date_uncertain=True,
            ))
    return list({article.url: article for article in articles}.values())


def parse_generic_article(html: str, source: str, url: str, outlet: str | None = None) -> RawArticle:
    soup = BeautifulSoup(html, "html.parser")
    data = _json_ld(soup)
    container = soup.select_one("article") or soup.select_one(".item-body") or soup.body
    content, tier = _body(container, data, "p", min_length=20)
    published = text.clean(data.get("datePublished"))
    return RawArticle(
        source=source,
        url=url,
        title=text.clean(data.get("headline") or _text(soup.select_one("h1"))),
        lead=text.clean(data.get("description") or _text(soup.select_one(".lead, .summary"))),
        content=content,
        original_outlet=outlet,
        published_at=published or None,
        date_uncertain=not published,
        extraction_tier=tier,
    )


def shahrekhabar_target(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if iframe := soup.select_one("iframe[src]"):
        return urljoin(page_url, iframe["src"])
    if refresh := soup.select_one('meta[http-equiv="refresh" i][content*="url=" i]'):
        return urljoin(page_url, refresh["content"].split("url=", 1)[-1].strip())
    return page_url


# ---------------------------------------------------------------------------- fetching


def _get(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, headers=USER_AGENT, timeout=TIMEOUT)
    response.raise_for_status()
    return response


def _fetch_rss(spec: SourceSpec, session: requests.Session, response, limit: int) -> list[RawArticle]:
    # The feed carries only a short description, so without fetching the page every article
    # from this source reached the classifier with ~150 characters while others supplied
    # 1,300+. Fall back to the feed entry when the page cannot be fetched.
    articles = []
    for entry in parse_mehr_feed(response.text)[:limit]:
        try:
            page = _get(session, entry.url)
        except requests.RequestException:
            articles.append(replace(entry, extraction_tier="feed"))
            continue
        full = parse_generic_article(page.text, entry.source, entry.url, entry.original_outlet)
        articles.append(replace(
            entry,
            content=full.content or entry.content,
            lead=entry.lead or full.lead,
            title=entry.title or full.title,
            published_at=entry.published_at or full.published_at,
            extraction_tier=full.extraction_tier if full.content else "feed",
        ))
    return articles


def _fetch_listing_detail(spec: SourceSpec, session: requests.Session, response, limit: int) -> list[RawArticle]:
    return [
        parse_khabarfoori_article(_get(session, url).text, url)
        for url in parse_khabarfoori_listing(response.text, spec.url)[:limit]
    ]


def _fetch_listing_relay(spec: SourceSpec, session: requests.Session, response, limit: int) -> list[RawArticle]:
    articles = []
    for listed in parse_shahrekhabar_listing(response.text, spec.url):
        try:
            relay = _get(session, listed.url)
            target = shahrekhabar_target(relay.text, listed.url)
            detail = relay if target == listed.url else _get(session, target)
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


# Keyed by SourceSpec.strategy. A new source that fits an existing shape is a config entry
# only; a genuinely new page shape adds one function here and fetch() never changes.
_STRATEGIES = {
    "rss": _fetch_rss,
    "listing_detail": _fetch_listing_detail,
    "listing_relay": _fetch_listing_relay,
}


def fetch(spec: SourceSpec, session: requests.Session | None = None, *, limit: int = 25) -> list[RawArticle]:
    """Fetch one source. Network failures propagate so the caller can mark it degraded."""
    handler = _STRATEGIES.get(spec.strategy)
    if handler is None:
        raise ValueError(f"unsupported strategy {spec.strategy!r}")
    session = session or requests.Session()
    return handler(spec, session, _get(session, spec.url), limit)


# --------------------------------------------------------------------------- backfill

# Historical pagination, keyed by source NAME rather than strategy: sharing a fetch shape
# does not mean sharing a history mechanism (Mehr's RSS feed and its archive are unrelated
# URLs). Shahrekhabar has no archive endpoint, so it is absent and /ops says so honestly.
#
# The page cap is a runaway guard, not a target depth - the real stop conditions are
# since_date and the stale-page counter. Each page costs one listing fetch plus one detail
# fetch per new article, so a wide window against a busy source is slow; that is the price
# of actually reaching the window's floor. 500 matches legacy's own HARD_MAX_PAGES.
_MAX_BACKFILL_PAGES = 500
_STALE_PAGE_LIMIT = 2  # consecutive pages with zero new URLs before giving up
_MEHR_ARCHIVE_URL = "https://www.mehrnews.com/archive"
_MEHR_ARCHIVE_CATEGORIES = (25, 7, 6)  # economics, politics, society - Mehr's own topic ids


def _paginate(
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
    published before `since_date`. `seen` is mutated so callers can share dedup state."""
    stale = 0
    for page in range(1, _MAX_BACKFILL_PAGES + 1):
        try:
            response = _get(session, page_url(page))
        except requests.RequestException:
            return
        new_urls = [u for u in parse_listing(response.text, listing_base_url) if u not in seen]
        if not new_urls:
            stale += 1
            if stale >= _STALE_PAGE_LIMIT:
                return
            continue
        stale = 0
        reached = False
        for url in new_urls:
            seen.add(url)
            try:
                detail = _get(session, url)
            except requests.RequestException:
                continue
            article = parse_article(detail.text, url)
            yield article
            reached |= bool(article.published_at and article.published_at < since_date)
        if reached:
            return


def _backfill_khabarfoori(spec, session, *, since_date, seen):
    yield from _paginate(
        session,
        page_url=lambda page: spec.url if page == 1 else f"{spec.url}/?page={page}",
        parse_listing=parse_khabarfoori_listing,
        listing_base_url=spec.url,
        parse_article=parse_khabarfoori_article,
        since_date=since_date,
        seen=seen,
    )


def _backfill_mehr(spec, session, *, since_date, seen):
    for topic in _MEHR_ARCHIVE_CATEGORIES:
        yield from _paginate(
            session,
            page_url=lambda page, topic=topic: f"{_MEHR_ARCHIVE_URL}?tp={topic}&pi={page}",
            parse_listing=parse_mehr_archive_listing,
            listing_base_url=_MEHR_ARCHIVE_URL,
            parse_article=lambda html, url: parse_generic_article(html, "mehr", url, "مهر"),
            since_date=since_date,
            seen=seen,
        )


# Keyed by source NAME, so a source with no entry yields nothing rather than falling
# through to another source's archive. BACKFILLABLE is derived from this table for the
# same reason - the set and the dispatch cannot drift apart.
_BACKFILL = {"khabarfoori": _backfill_khabarfoori, "mehr": _backfill_mehr}
BACKFILLABLE = frozenset(_BACKFILL)


def backfill_fetch(
    spec: SourceSpec, session: requests.Session | None = None, *, since_date: str, known_urls: set[str]
) -> Iterator[RawArticle]:
    """Paginate a source back to `since_date` (Gregorian 'YYYY-MM-DD'). Sources without a
    history mechanism yield nothing."""
    handler = _BACKFILL.get(spec.name)
    if handler is not None:
        yield from handler(spec, session or requests.Session(),
                           since_date=since_date, seen=set(known_urls))
