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
def test_a_404_is_gone_and_is_not_retried(image_row, monkeypatch):
    """Unit: a deleted CDN object is a fact, not a Transient. The hourly sweep was
    re-queuing 404s forever because the status stayed PENDING."""
    from articles.models import ArticleImage, ImageStatus
    from articles.tasks import download_image

    monkeypatch.setattr(
        "articles.tasks.open_checked",
        lambda *a, **k: FakeResponse(0, status_code=404),
    )
    result = download_image(image_row.article_id)
    stored = ArticleImage.objects.get(pk=image_row.pk)
    assert result["status"] == "gone"
    assert stored.status == ImageStatus.GONE


@pytest.mark.django_db
def test_an_unreachable_host_is_failed_without_celery_retry(image_row, monkeypatch):
    """Unit: a DNS/connect timeout is a fact about this VPS's path to that CDN.

    Live: cdn.mashreghnews.ir does not resolve from the production host (5s DNS
    timeout), 757 rows failed, 0 stored, crawl worker at 90% of 640MB. Retrying
    Transient three times triples that wait and never stores a file.
    """
    from articles.models import ArticleImage, ImageStatus
    from articles.tasks import download_image
    from core.errors import Transient

    def unreachable(*args, **kwargs):
        raise Transient("fetch failed: connection to cdn.example timed out")

    monkeypatch.setattr("articles.tasks.open_checked", unreachable)
    monkeypatch.setattr("articles.tasks._remember_dead_image_host", lambda host: None)
    result = download_image(image_row.article_id)

    assert result["status"] == "failed"
    stored = ArticleImage.objects.get(pk=image_row.pk)
    assert stored.status == ImageStatus.FAILED
    assert "timed out" in stored.error


@pytest.mark.django_db
def test_pending_sweep_skips_a_host_already_known_unreachable(image_row, monkeypatch):
    """Unit: after one timeout, later pictures for that host must not be queued."""
    from articles.models import ArticleImage, ImageStatus
    from articles.tasks import download_pending_images

    queued = []
    monkeypatch.setattr("articles.tasks.image_host_is_dead", lambda host: True)
    monkeypatch.setattr(
        "articles.tasks.download_image",
        type("Stub", (), {"delay": staticmethod(lambda pk: queued.append(pk))}),
    )
    result = download_pending_images(limit=10)

    assert queued == []
    assert result["queued"] == 0
    assert result["skipped_dead_host"] == 1
    assert ArticleImage.objects.get(pk=image_row.pk).status == ImageStatus.FAILED


@pytest.mark.django_db
def test_a_redirect_loop_stops_being_pending(image_row, monkeypatch):
    """Unit: a Permanent the body does not name must still hit on_failure.

    `open_checked` raises Permanent on a redirect loop. That is not Transient, so Celery
    does not retry it, and download_image does not catch it - the row would stay PENDING
    unless the base-class hook is actually wired.
    """
    from articles.models import ArticleImage, ImageStatus
    from articles.tasks import download_image
    from core.errors import Permanent

    def loop(*args, **kwargs):
        raise Permanent("more than 5 redirects")

    monkeypatch.setattr("articles.tasks.open_checked", loop)
    result = download_image.apply(args=[image_row.article_id], throw=False)

    assert result.failed()
    stored = ArticleImage.objects.get(pk=image_row.pk)
    assert stored.status == ImageStatus.FAILED
    assert "redirects" in stored.error


@pytest.mark.django_db
def test_giving_up_never_overwrites_an_image_that_was_already_stored(image_row):
    """A late failure must not undo a success. `on_failure` fires outside the task body,
    so it is the one place that can reach a row another attempt has already finished."""
    from articles.models import ArticleImage, ImageStatus
    from articles.tasks import download_image

    ArticleImage.objects.filter(pk=image_row.pk).update(status=ImageStatus.STORED)
    download_image.on_failure(
        Exception("late timeout"), "task-id", [image_row.article_id], {}, None
    )

    assert ArticleImage.objects.get(pk=image_row.pk).status == ImageStatus.STORED


@pytest.mark.django_db
def test_the_pending_sweep_takes_the_newest_images_first(image_row, make_article):
    """Unordered `LIMIT` let one stuck CDN occupy all 200 slots of every hourly sweep, so
    images from hosts that work were never reached. Newest-first is also deterministic,
    which unordered was not."""
    from articles.models import ArticleImage
    from articles.tasks import download_pending_images

    newer = ArticleImage.objects.create(
        article=make_article(), source_url="https://cdn.example/newer.jpg"
    )
    queued = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "articles.tasks.download_image",
            type("Stub", (), {"delay": staticmethod(lambda pk: queued.append(pk))}),
        )
        download_pending_images(limit=1)

    assert queued == [newer.article_id]


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
