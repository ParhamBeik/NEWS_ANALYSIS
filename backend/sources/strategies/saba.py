"""Saba/Nastooh newsroom RSS: Mehr, IRNA and ISNA.

All three run the same CMS ("Saba Enterprise Newsroom", generator tag `www.nastooh.ir`)
and emit an identical item shape, verified live against all three feeds. One strategy
therefore serves three sources, and a fourth agency on the same CMS is a config row.

Two fields the previous implementation discarded on every single item:

- `<enclosure url=... type="image/jpeg">` - the headline image, published right there in
  the feed. No page fetch, no og:image guessing.
- `<category domain="gilan">استانها > گیلان</category>` - the newsroom's OWN taxonomy
  slug. This is free classification signal: provincial and sports desks are reliably not
  security or macroeconomics, and every one of those articles was costing a paid LLM call.

The feed's `<description>` is a ~150-character teaser, so the article page is still
fetched for the body - without it these sources reached the classifier with a tenth of
the evidence the others supplied. When the page cannot be fetched the feed entry is kept
at tier `feed` rather than dropped.
"""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from core.errors import Permanent
from core.text import clean

from ..extraction import RawArticle, fetch_text, parse_generic_article

CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"


def parse_feed(xml: str, source: str, outlet: str) -> list[RawArticle]:
    """RSS items -> RawArticle, using only what the feed itself carries."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        # A feed that stopped being XML is a site change, not a blip: retrying it just
        # spends the retry budget on the same broken bytes.
        raise Permanent(f"{source}: feed is not valid XML: {exc}") from exc

    def field(item, name: str) -> str:
        return clean(item.findtext(name, default=""))

    articles = []
    for item in root.findall(".//item"):
        try:
            published = parsedate_to_datetime(field(item, "pubDate")).isoformat()
        except (TypeError, ValueError):
            published = ""

        enclosure = item.find("enclosure")
        image_url = ""
        if enclosure is not None and str(enclosure.get("type", "")).startswith("image/"):
            image_url = clean(enclosure.get("url", ""))

        category = item.find("category")
        native_category = ""
        if category is not None:
            # The `domain` attribute is the machine slug ("gilan", "soccer"); the element
            # text is a Persian breadcrumb. The slug is the stable one to key config on.
            native_category = clean(category.get("domain", "")).lower()

        # The full body is occasionally inlined in content:encoded. Free when present -
        # measured empty on all three feeds today, but costs nothing to keep reading.
        encoded = clean(item.findtext(CONTENT_NS, default=""))
        description = field(item, "description")

        articles.append(
            RawArticle(
                source=source,
                url=field(item, "link"),
                title=field(item, "title"),
                lead=description,
                content=encoded or description,
                original_outlet=outlet,
                published_at=published or None,
                date_uncertain=not published,
                extraction_tier="feed",
                native_category=native_category,
                image_url=image_url,
            )
        )
    return [article for article in articles if article.url and article.title]


def fetch(spec, session: requests.Session, *, limit: int) -> list[RawArticle]:
    outlet = spec.display_name or spec.name
    entries = parse_feed(fetch_text(session, spec.url), spec.name, outlet)[:limit]

    articles = []
    for entry in entries:
        try:
            page = fetch_text(session, entry.url)
        except Exception:
            # One unreachable article page must not fail the whole feed. The entry still
            # carries a title, a date, an image and a category - enough to store and to
            # notice later that its body never arrived.
            articles.append(entry)
            continue
        full = parse_generic_article(page, entry.source, entry.url, entry.original_outlet)
        articles.append(
            RawArticle(
                source=entry.source,
                url=entry.url,
                title=entry.title or full.title,
                lead=entry.lead or full.lead,
                content=full.content or entry.content,
                original_outlet=entry.original_outlet,
                published_at=entry.published_at or full.published_at,
                date_uncertain=entry.date_uncertain and full.date_uncertain,
                extraction_tier=full.extraction_tier if full.content else "feed",
                # Feed metadata wins over the page: the newsroom's own taxonomy slug and
                # published enclosure are authoritative, the page markup is inferred.
                native_category=entry.native_category or full.native_category,
                keywords=full.keywords,
                image_url=entry.image_url or full.image_url,
            )
        )
    return articles


def backfill(spec, session: requests.Session, *, since_date: str, seen: set[str]):
    """Paginate the newsroom archive. Mehr's archive and its RSS feed are unrelated URLs,
    which is why the archive endpoint is its own field rather than derived from `url`."""
    from urllib.parse import urljoin

    from ..extraction import soup_of
    from .pagination import paginate

    def parse_listing(html: str, base_url: str) -> list[str]:
        soup = soup_of(html)
        return list(
            dict.fromkeys(
                urljoin(base_url, link["href"])
                for link in soup.select("li.news div.desc h3 a[href], .news-list a[href]")
            )
        )

    outlet = spec.display_name or spec.name
    yield from paginate(
        session,
        page_url=lambda page: f"{spec.archive_url}?pi={page}",
        parse_listing=parse_listing,
        listing_base_url=spec.archive_url,
        parse_article=lambda html, url: parse_generic_article(html, spec.name, url, outlet),
        since_date=since_date,
        seen=seen,
    )
