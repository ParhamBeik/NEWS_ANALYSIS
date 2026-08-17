import argparse
from datetime import datetime, timedelta, timezone

from news_intel import cli, sources
from news_intel.core import config, db
from news_intel.providers import RuleProvider
from news_intel.sources import RawArticle


class Recording(RuleProvider):
    """A provider with its own identity, standing in for a real paid provider."""


def test_backfilled_articles_always_classify_on_rule_never_the_runs_real_provider(tmp_path, monkeypatch):
    """A coverage gap can mean hundreds of articles - paying to label all of them as a
    silent side effect of a routine `run --provider gapgpt` would be a real-money surprise,
    not something the $1 budget ceiling catching it after the fact makes acceptable."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "news.db")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        cli, "resolve_providers",
        lambda choice: {node: Recording(name="real-provider", model="m1") for node in ("classify", "evaluate", "summarize")},
    )

    def fake_fetch(spec, session=None, *, limit=25):
        return [RawArticle(
            source=spec.name, url=f"https://test/{spec.name}/main",
            title="حمله موشکی به تاسیسات نفتی کشور", lead="جزئیات حادثه",
            content="متن کامل خبر درباره حمله و اثر آن بر قیمت طلا و دلار در بازار داخلی.",
            published_at=datetime.now(timezone.utc).isoformat(),
        )]
    monkeypatch.setattr(sources, "fetch", fake_fetch)

    def fake_backfill_fetch(spec, session=None, *, since_date, known_urls):
        if spec.name != "khabarfoori":
            return
        yield RawArticle(
            source="khabarfoori", url="https://test/khabarfoori/backfilled",
            title="افزایش قیمت طلا و نگرانی امنیتی در بازار", lead="جزئیات",
            content="متن کامل خبر درباره حمله و اثر آن بر قیمت طلا و دلار در بازار داخلی.",
            published_at=(datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
        )
    monkeypatch.setattr(sources, "backfill_fetch", fake_backfill_fetch)

    args = argparse.Namespace(sources=None, limit=5, provider="gapgpt", export=False)
    cli.run_once(args)

    with db.connect(tmp_path / "news.db", readonly=True) as conn:
        providers = {
            row["url"]: row["provider"]
            for row in conn.execute(
                "SELECT a.url AS url, c.provider AS provider"
                " FROM articles a JOIN classifications c ON c.article_id = a.id"
            )
        }
    assert providers["https://test/khabarfoori/main"] == "real-provider"
    assert providers["https://test/khabarfoori/backfilled"] == "rule"
