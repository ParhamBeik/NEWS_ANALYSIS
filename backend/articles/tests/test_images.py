"""Image fetching, and the size cap that has to hold before the bytes arrive.

The interesting property is not "an oversized image is rejected" - it is that it is
rejected without being read. A worker with a 640 MB limit and four concurrent children
cannot afford to find out how large a response was by receiving all of it.
"""

from __future__ import annotations

import pytest

from articles.tasks import MAX_BYTES, _read_capped


class FakeResponse:
    """Just enough of `requests.Response` to observe how much was actually read.

    `response.content` is deliberately absent: touching it is the bug under test, so a
    regression here fails with an AttributeError rather than passing quietly.
    """

    def __init__(self, total_bytes: int, chunk_size: int = 64 * 1024):
        self.total_bytes = total_bytes
        self.chunk_size = chunk_size
        self.read_bytes = 0
        self.closed = False

    def iter_content(self, chunk_size: int):
        remaining = self.total_bytes
        while remaining > 0:
            if self.closed:  # a real connection stops producing once hung up on
                return
            size = min(chunk_size, remaining)
            remaining -= size
            self.read_bytes += size
            yield b"\0" * size

    def close(self):
        self.closed = True


class TestReadCapped:
    def test_a_small_image_is_read_whole(self):
        response = FakeResponse(1024)
        assert len(_read_capped(response)) == 1024

    def test_an_oversized_body_is_abandoned_rather_than_downloaded(self):
        """`stream=True` followed by `response.content` materialises the WHOLE body, so
        slicing afterwards trimmed a buffer that had already been read in full - a CDN
        serving 500 MB was downloaded entirely before being declared too large."""
        response = FakeResponse(500 * 1024 * 1024)
        payload = _read_capped(response)

        assert len(payload) == MAX_BYTES + 1, "the extra byte is what makes it detectable"
        assert response.closed, "the connection must be hung up on, not drained"
        # One chunk of overshoot is the cost of noticing; anything near the full body means
        # the cap is being applied after the download rather than during it.
        assert response.read_bytes < MAX_BYTES + 2 * response.chunk_size

    def test_a_body_exactly_at_the_limit_is_kept(self):
        assert len(_read_capped(FakeResponse(MAX_BYTES))) == MAX_BYTES


@pytest.mark.django_db
def test_an_oversized_image_is_recorded_as_failed_not_retried(make_article, monkeypatch):
    """A too-large image is a fact about the source, not a transient error: retrying it
    spends the same bandwidth again to reach the same conclusion."""
    from articles.models import ArticleImage, ImageStatus
    from articles.tasks import download_image

    article = make_article()
    ArticleImage.objects.create(article=article, source_url="https://cdn.example/huge.jpg")

    monkeypatch.setattr(
        "articles.tasks.build_session",
        lambda: type("S", (), {"get": lambda *a, **k: _oversized()})(),
    )
    result = download_image(article.pk)
    assert result["status"] == "too_large"
    assert ArticleImage.objects.get(article=article).status == ImageStatus.FAILED


def _oversized():
    response = FakeResponse(50 * 1024 * 1024)
    response.raise_for_status = lambda: None
    return response
