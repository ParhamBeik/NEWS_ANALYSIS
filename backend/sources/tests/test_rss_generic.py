"""An official RSS or Atom release still reaches the shared ingest shape."""

from unittest.mock import patch

import pytest

from sources.strategies import rss_generic


@pytest.mark.parametrize("xml", [
    '<rss><channel><item><title>Rate decision today</title><link>https://example.org/a</link><description>Policy &amp; markets</description><pubDate>Tue, 29 Sep 2026 12:00:00 GMT</pubDate></item></channel></rss>',
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Rate decision today</title><link href="https://example.org/a"/><summary>Policy &amp; markets</summary><updated>2026-09-29T12:00:00Z</updated></entry></feed>',
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><item><title>Rate decision today</title><link>https://example.org/a</link><description>Policy &amp; markets</description><dc:date>2026-09-29T12:00:00Z</dc:date></item></rdf:RDF>',
])
def test_generic_feed_extracts_provenance(xml):
    source = type("Source", (), {"name": "official", "url": "https://example.org/rss"})()
    with patch("sources.strategies.rss_generic.fetch_text", return_value=xml):
        rows = rss_generic.fetch(source, None, limit=10)
    assert len(rows) == 1
    assert rows[0].url == "https://example.org/a"
    assert rows[0].title == "Rate decision today"
    assert rows[0].extraction_tier == "feed"
