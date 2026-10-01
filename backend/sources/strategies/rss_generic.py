"""Standard RSS/Atom headlines from primary institutions and permitted public feeds."""

from __future__ import annotations

from datetime import UTC
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from core.errors import Permanent
from sources.extraction import RawArticle, fetch_text

RSS1 = "{http://purl.org/rss/1.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"


def _text(node, *names):
    for name in names:
        found = node.find(name)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def _date(value: str) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        return value


def fetch(source, session, *, limit: int) -> list[RawArticle]:
    xml = fetch_text(session, source.url)
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise Permanent(f"invalid RSS/Atom for {source.name}") from exc
    items = (
        root.findall(".//item")
        or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        or root.findall(f".//{RSS1}item")
    )
    if not items:
        raise Permanent(f"RSS/Atom feed has no entries for {source.name}")
    rows = []
    for item in items[:limit]:
        title = _text(item, "title", "{http://www.w3.org/2005/Atom}title", f"{RSS1}title")
        url = _text(item, "link", f"{RSS1}link")
        if not url:
            links = item.findall("{http://www.w3.org/2005/Atom}link")
            link = next((row for row in links if row.get("rel", "alternate") == "alternate"), None)
            url = link.get("href", "") if link is not None else ""
        if not title or not url:
            continue
        lead_html = _text(item, "description", "{http://www.w3.org/2005/Atom}summary", f"{RSS1}description")
        lead = BeautifulSoup(lead_html, "html.parser").get_text(" ", strip=True)
        published = _text(
            item, "pubDate", "{http://www.w3.org/2005/Atom}published",
            "{http://www.w3.org/2005/Atom}updated", f"{DC}date",
        )
        rows.append(RawArticle(
            source=source.name, url=url, title=title, lead=lead,
            published_at=_date(published), extraction_tier="feed",
        ))
    return rows
