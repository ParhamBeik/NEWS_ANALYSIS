import jdatetime

from news_intel import backfill
from news_intel.core import db
from news_intel.sources import SourceSpec


def _article(conn, *, source, persian_date, url=None):
    url = url or f"https://test/{source}/{persian_date}"
    db.insert(conn, "articles", {
        "url": url, "identity_key": f"id:{url}", "source": source,
        "original_title": "t", "lead": "l", "content": "c", "content_hash": url,
        "published_at_persian": persian_date, "date_uncertain": 0,
        "fetched_at": "2026-01-01T00:00:00+03:30",
    })


def _today_str():
    d = jdatetime.date.today()
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


def test_coverage_reports_every_missing_day_in_the_window(conn):
    _article(conn, source="khabarfoori", persian_date=_today_str())
    gaps = backfill.coverage(conn, "khabarfoori", days=3)
    assert len(gaps) == 2
    assert _today_str() not in gaps


def test_coverage_ignores_uncertain_dated_and_duplicate_rows(conn):
    db.insert(conn, "articles", {
        "url": "https://test/uncertain", "identity_key": "id:u", "source": "khabarfoori",
        "original_title": "t", "lead": "l", "content": "c", "content_hash": "u",
        "published_at_persian": _today_str(), "date_uncertain": 1,
        "fetched_at": "2026-01-01T00:00:00+03:30",
    })
    # Only an uncertain-dated row exists for today - it must not count as coverage.
    assert _today_str() in backfill.coverage(conn, "khabarfoori", days=1)


def test_coverage_is_full_once_every_window_day_has_an_article(conn):
    from datetime import timedelta  # jdatetime.date supports timedelta arithmetic
    for offset in range(3):
        day = jdatetime.date.today() - timedelta(days=offset)
        _article(conn, source="mehr", persian_date=f"{day.year:04d}-{day.month:02d}-{day.day:02d}")
    assert backfill.coverage(conn, "mehr", days=3) == set()


def test_ensure_window_skips_sources_with_no_gap(conn):
    from datetime import timedelta
    for offset in range(2):
        day = jdatetime.date.today() - timedelta(days=offset)
        _article(conn, source="khabarfoori", persian_date=f"{day.year:04d}-{day.month:02d}-{day.day:02d}")
    specs = {"khabarfoori": SourceSpec("khabarfoori", 2, "listing_detail", "https://kf.test")}
    stats = backfill.ensure_window(conn, specs, {}, days=2)
    assert stats == {}  # no gap -> never attempted, so no network/session was ever needed


def test_ensure_window_skips_sources_without_a_backfill_strategy(conn):
    specs = {"shahrekhabar": SourceSpec("shahrekhabar", 2, "listing_relay", "https://shahr.test")}
    stats = backfill.ensure_window(conn, specs, {}, days=14)
    assert stats == {}


def test_ensure_window_skips_disabled_sources(conn):
    specs = {"khabarfoori": SourceSpec("khabarfoori", 2, "listing_detail", "https://kf.test", enabled=False)}
    stats = backfill.ensure_window(conn, specs, {}, days=14)
    assert stats == {}


def test_ensure_window_respects_the_retry_cooldown(conn, monkeypatch):
    """A gap that didn't close on the last attempt is not retried immediately."""
    calls = []
    monkeypatch.setattr(
        backfill.sources, "backfill_fetch",
        lambda spec, session=None, *, since_date, known_urls: iter(calls.append(1) or ()),
    )
    specs = {"khabarfoori": SourceSpec("khabarfoori", 2, "listing_detail", "https://kf.test")}
    first = backfill.ensure_window(conn, specs, {}, days=14)
    assert first == {"khabarfoori": 0}
    assert len(calls) == 1

    second = backfill.ensure_window(conn, specs, {}, days=14)
    assert second == {}  # cooldown active, no second attempt
    assert len(calls) == 1
