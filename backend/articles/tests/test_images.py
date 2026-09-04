"""Image fetching: what gets stored, and what gets refused.

The size cap and the address guard themselves are tested in `core/tests/test_net.py`. What
matters here is that this task routes both of them to the same place - a row marked FAILED
with the reason on it - rather than raising, because a picture is decoration and the story
is the product. A retry on either would spend the same bandwidth to reach the same answer.
"""

from __future__ import annotations

import pytest

from articles.tasks import MAX_BYTES
from core.net import BlockedURL
from core.tests.test_net import FakeResponse


@pytest.fixture
def image_row(make_article, db):
    from articles.models import ArticleImage

    article = make_article()
    return ArticleImage.objects.create(
        article=article, source_url="https://cdn.example/huge.jpg"
    )


@pytest.mark.django_db
def test_an_oversized_image_is_recorded_as_failed_not_retried(image_row, monkeypatch):
    """A too-large image is a fact about the source, not a transient error."""
    from articles.models import ArticleImage, ImageStatus
    from articles.tasks import download_image

    monkeypatch.setattr(
        "articles.tasks.open_checked",
        lambda *a, **k: FakeResponse(MAX_BYTES + 50 * 1024 * 1024),
    )
    result = download_image(image_row.article_id)

    assert result["status"] == "too_large"
    assert ArticleImage.objects.get(pk=image_row.pk).status == ImageStatus.FAILED


@pytest.mark.django_db
def test_an_image_url_pointing_into_our_own_network_is_refused(image_row, monkeypatch):
    """This URL came out of a third party's og:image tag and this worker sits on the same
    private network as Postgres and Redis. The refusal has to be recorded, not raised: a
    Transient here would retry a request forgery attempt three times with backoff."""
    from articles.models import ArticleImage, ImageStatus
    from articles.tasks import download_image

    def refuse(*args, **kwargs):
        raise BlockedURL("cdn.example resolves to non-public address 127.0.0.1")

    monkeypatch.setattr("articles.tasks.open_checked", refuse)
    result = download_image(image_row.article_id)

    stored = ArticleImage.objects.get(pk=image_row.pk)
    assert result["status"] == "blocked"
    assert stored.status == ImageStatus.FAILED
    assert "non-public" in stored.error
