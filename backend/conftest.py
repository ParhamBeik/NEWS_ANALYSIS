"""Shared fixtures.

Deliberately plain object creation rather than factory_boy for the core entities: these
fixtures are read by anyone debugging a failing invariant test, and an explicit row is
easier to reason about than a factory's defaults when the question is "what exactly was
stored?".
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from articles.models import Article
from core.text import content_hash
from inference.models import PromptVariant
from sources.models import Source, Strategy


@pytest.fixture(autouse=True)
def _reset_throttle_counters():
    """Rate-limit state lives in the cache, and the cache is not reset between tests.

    Without this, a test that signs up is spending the NEXT test's allowance, and the suite
    starts failing on ordering rather than on behaviour. The throttle tests still assert the
    limit explicitly - this only guarantees each test begins with a full one.
    """
    from django.core.cache import cache

    cache.clear()
    yield


@pytest.fixture(autouse=True)
def _isolate_provider_circuit(db, request):
    """Dispatch tests assume a closed circuit. Production starts paused."""
    from inference.circuit import close
    from inference.models import ProviderCircuit

    if request.node.get_closest_marker("fresh_circuit"):
        ProviderCircuit.objects.all().delete()
        yield
        return
    close("test isolation")
    yield


@pytest.fixture
def source(db) -> Source:
    return Source.objects.create(
        name="mehr",
        display_name="Mehr News",
        strategy=Strategy.RSS_SABA,
        url="https://www.mehrnews.com/rss",
        archive_url="https://www.mehrnews.com/archive",
        tier=1,
        priority=2,
    )


@pytest.fixture
def make_article(db, source):
    counter = {"n": 0}

    def _make(**overrides) -> Article:
        counter["n"] += 1
        n = counter["n"]
        fields = {
            "url": f"https://www.mehrnews.com/news/{n}",
            "source": source,
            "original_title": f"تیتر خبر شماره {n}",
            "lead": "خلاصه خبر",
            "content": "متن کامل خبر برای آزمایش خط لوله.",
            "published_at": timezone.now(),
            "fetched_at": timezone.now(),
        }
        fields.update(overrides)
        fields.setdefault(
            "content_hash",
            content_hash(fields["original_title"], fields["lead"], fields["content"]),
        )
        return Article.objects.create(**fields)

    return _make


@pytest.fixture
def article(make_article) -> Article:
    return make_article()


@pytest.fixture
def variant(db) -> PromptVariant:
    return PromptVariant.objects.create(
        name="control", model="gemini-2.5-flash-lite", is_active=True
    )


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="analyst", password="test-pass")
