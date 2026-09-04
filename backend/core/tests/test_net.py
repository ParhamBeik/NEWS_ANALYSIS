"""Outbound-fetch guards.

Two properties are under test, and they fail in different ways:

- WHAT WE REFUSE TO CONNECT TO. The crawler follows links and image URLs written by a third
  party, from a worker on the same private network as Postgres and Redis. The check has to
  be on the RESOLVED ADDRESS, because a hostile page can just as easily name `db` or a
  public hostname whose A record answers 127.0.0.1.

- HOW MUCH WE READ. `response.text` materialises the whole body whatever its size. The
  interesting property is not "an oversized body is rejected" - it is that it is rejected
  WITHOUT being read, because a worker with a 640 MB limit and four concurrent children
  cannot afford to find out how large a response was by receiving all of it.

Every address case uses a literal IP so `getaddrinfo` does no DNS and the suite stays
offline; the one hostname case patches resolution explicitly, which is the point it proves.
"""

from __future__ import annotations

import socket

import pytest

from core.errors import Permanent, Transient
from core.net import (
    MAX_BODY_BYTES,
    MAX_REDIRECTS,
    BlockedURL,
    check_url,
    open_checked,
    read_capped,
)


class TestCheckURL:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",            # loopback
            "http://[::1]/x",                # loopback, v6
            "http://10.0.0.5/x",             # RFC1918
            "http://192.168.1.1/x",
            "http://172.16.0.1/x",
            # The cloud metadata endpoint. The single most valuable SSRF target there is,
            # and it is reachable by IP with no DNS at all.
            "http://169.254.169.254/latest/meta-data/",
            "http://0.0.0.0/x",
        ],
    )
    def test_private_and_reserved_addresses_are_refused(self, url):
        with pytest.raises(BlockedURL):
            check_url(url)

    def test_a_public_address_is_allowed(self):
        check_url("http://93.184.216.34/index.html")

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x/1", "ftp://x/y", "//x/y"])
    def test_only_http_and_https_are_allowed(self, url):
        """`requests` will accept a scheme we never intended. An allow-list is the only
        version of this that stays correct as schemes are added."""
        with pytest.raises(BlockedURL):
            check_url(url)

    def test_the_check_is_on_the_resolved_address_not_the_name(self, monkeypatch):
        """A perfectly ordinary-looking hostname whose DNS answers 127.0.0.1 is the whole
        reason a hostname allow-list would not be a control."""
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **k: [(None, None, None, "", ("127.0.0.1", 0))],
        )
        with pytest.raises(BlockedURL):
            check_url("http://images.example.com/photo.jpg")

    def test_every_resolved_address_must_be_public_not_just_the_first(self, monkeypatch):
        """A name with one public and one private record would otherwise pass the check and
        then connect to whichever the resolver happened to prefer."""
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **k: [
                (None, None, None, "", ("93.184.216.34", 0)),
                (None, None, None, "", ("10.1.2.3", 0)),
            ],
        )
        with pytest.raises(BlockedURL):
            check_url("http://mixed.example.com/x")

    def test_a_name_that_does_not_resolve_is_transient_not_blocked(self, monkeypatch):
        """DNS is the one genuinely flaky part of this. A blocked address resolves the same
        way forever and must not be retried; an unresolvable name may come back."""
        def boom(*args, **kwargs):
            raise socket.gaierror("nope")

        monkeypatch.setattr(socket, "getaddrinfo", boom)
        with pytest.raises(Transient):
            check_url("http://gone.example.com/x")

    def test_blocked_is_permanent_so_it_is_never_retried(self):
        assert issubclass(BlockedURL, Permanent)


class FakeResponse:
    """Just enough of `requests.Response` to observe how much was actually read.

    `content` is deliberately absent: touching it is the bug under test, so a regression
    fails with an AttributeError rather than passing quietly.
    """

    def __init__(self, total_bytes: int = 0, chunk_size: int = 64 * 1024, **attrs):
        self.total_bytes = total_bytes
        self.chunk_size = chunk_size
        self.read_bytes = 0
        self.closed = False
        self.is_redirect = False
        self.is_permanent_redirect = False
        self.status_code = 200
        self.encoding = "utf-8"
        self.headers: dict[str, str] = {}
        self.__dict__.update(attrs)

    def iter_content(self, chunk_size: int):
        remaining = self.total_bytes
        while remaining > 0:
            if self.closed:  # a real connection stops producing once hung up on
                return
            size = min(chunk_size, remaining)
            remaining -= size
            self.read_bytes += size
            yield b"\0" * size

    def raise_for_status(self):
        return None

    def close(self):
        self.closed = True


class TestReadCapped:
    def test_a_small_body_is_read_whole(self):
        assert len(read_capped(FakeResponse(1024))) == 1024

    def test_an_oversized_body_is_abandoned_rather_than_downloaded(self):
        response = FakeResponse(500 * 1024 * 1024)
        payload = read_capped(response)

        assert len(payload) == MAX_BODY_BYTES + 1, "the extra byte is what makes it detectable"
        assert response.closed, "the connection must be hung up on, not drained"
        # One chunk of overshoot is the cost of noticing; anything near the full body means
        # the cap is applied after the download rather than during it.
        assert response.read_bytes < MAX_BODY_BYTES + 2 * response.chunk_size

    def test_a_body_exactly_at_the_limit_is_kept(self):
        assert len(read_capped(FakeResponse(MAX_BODY_BYTES))) == MAX_BODY_BYTES

    def test_the_cap_is_caller_settable(self):
        assert len(read_capped(FakeResponse(4096), 1024)) == 1025


class RecordingSession:
    """A session that replays a scripted sequence and records what it was asked for."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requested: list[str] = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        return self.responses.pop(0)


def _redirect_to(location: str) -> FakeResponse:
    return FakeResponse(is_redirect=True, status_code=302, headers={"location": location})


class TestRedirects:
    def test_a_redirect_into_the_private_network_is_refused(self):
        """The reason `allow_redirects=True` cannot be used. A permitted public host that
        302s to `http://redis:6379/` would otherwise be followed with no second check, which
        makes the first check decorative."""
        session = RecordingSession(_redirect_to("http://127.0.0.1:6379/"))
        with pytest.raises(BlockedURL):
            open_checked(session, "http://93.184.216.34/x", timeout=5)
        assert session.requested == ["http://93.184.216.34/x"], "the hop was not followed"

    def test_a_redirect_to_a_public_host_is_followed(self):
        session = RecordingSession(
            _redirect_to("http://93.184.216.35/final"), FakeResponse(16)
        )
        response = open_checked(session, "http://93.184.216.34/x", timeout=5)
        assert response.status_code == 200
        assert session.requested[-1] == "http://93.184.216.35/final"

    def test_a_relative_redirect_resolves_against_the_current_url(self):
        session = RecordingSession(_redirect_to("/moved"), FakeResponse(16))
        open_checked(session, "http://93.184.216.34/x", timeout=5)
        assert session.requested[-1] == "http://93.184.216.34/moved"

    def test_a_redirect_loop_terminates(self):
        session = RecordingSession(
            *[_redirect_to("http://93.184.216.34/x") for _ in range(MAX_REDIRECTS + 2)]
        )
        with pytest.raises(Permanent):
            open_checked(session, "http://93.184.216.34/x", timeout=5)

    def test_a_redirect_with_no_location_is_permanent(self):
        session = RecordingSession(FakeResponse(is_redirect=True, status_code=302))
        with pytest.raises(Permanent):
            open_checked(session, "http://93.184.216.34/x", timeout=5)
