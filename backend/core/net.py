"""Outbound fetching for URLs this system did not choose.

Only the first hop of a crawl is trusted. Everything after it is supplied by a third-party
page: a Khabarfoori listing hands us the detail links, a Shahrekhabar interstitial names
its own redirect target in an `<iframe src>` or a `<meta refresh>`, and every article page
names its headline image in its own JSON-LD or `og:image`. Those fetches then run inside a
Celery worker sitting on the compose `internal` network next to Postgres and Redis, so
"fetch whatever the page said" is a server-side request forgery primitive aimed at our own
infrastructure - `http://redis:6379/`, `http://backend:8000/api/...`, `http://169.254.169.254/`.

Three guards, and each one covers a hole the others do not:

- SCHEME. `requests` is happy to be handed a scheme we never intended; only http and https
  are ever legitimate here.
- RESOLVED ADDRESS, not hostname. Checking the name would miss `db`, `localhost` and any
  public name whose DNS record simply answers 127.0.0.1.
- REDIRECTS, one hop at a time. `allow_redirects=True` would follow a permitted public host
  straight to an internal one without a second check, which defeats the point of the first
  check entirely.

What this does NOT close is DNS rebinding: the address is resolved here and resolved again
by the connection, and a record that answers differently between the two would slip past.
Closing that needs the socket pinned to the address we validated. Given the threat model -
markup on an Iranian news site, not an attacker with authoritative DNS aimed at us - the
remaining gap is much smaller than the one being closed, and stating it is better than
implying it is covered.

Bodies are also capped. `response.text` reads the whole body into memory whatever its size,
and these workers run under a 640 MB limit with four children; a source serving a
multi-gigabyte response should fail, not take the pool down with it.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

from .errors import Permanent, Transient

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 5
# Generous for an article page (the largest measured is ~400 KB) and far below anything
# that would threaten a worker.
MAX_BODY_BYTES = 10 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


class BlockedURL(Permanent):
    """A URL that points somewhere we refuse to fetch from.

    Permanent, not Transient: the same URL resolves to the same address on every attempt,
    so a retry only spends the retry budget proving that.
    """


def _resolved_addresses(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        # A name that does not resolve right now may resolve later - DNS is the one part of
        # this that is legitimately flaky - so this is Transient while a blocked address is
        # not.
        raise Transient(f"could not resolve {host!r}: {exc}") from exc
    return {ipaddress.ip_address(info[4][0]) for info in infos}


def check_url(url: str) -> None:
    """Raise unless `url` is an http(s) URL whose every resolved address is public.

    EVERY address, not the first: a name with both a public A record and a private one
    would otherwise pass the check and then connect to whichever the resolver preferred.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise BlockedURL(f"refusing scheme {parsed.scheme!r} for {url[:200]}")
    host = parsed.hostname
    if not host:
        raise BlockedURL(f"no host in {url[:200]}")
    for address in _resolved_addresses(host):
        # `is_global` is the IANA special-purpose registry, so one check covers loopback,
        # RFC1918, link-local (including the cloud metadata address), carrier-grade NAT,
        # multicast and the unspecified address.
        if not address.is_global:
            raise BlockedURL(f"{host} resolves to non-public address {address}")


def open_checked(
    session: requests.Session, url: str, *, timeout: int, stream: bool = False
) -> requests.Response:
    """GET `url`, validating it and every redirect target it leads to.

    The response is returned open when `stream=True`; the caller owns closing it.
    """
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        try:
            response = session.get(url, timeout=timeout, stream=stream, allow_redirects=False)
        except requests.RequestException as exc:
            raise Transient(f"fetch failed: {exc}") from exc
        if not response.is_redirect and not response.is_permanent_redirect:
            return response
        location = response.headers.get("location", "")
        response.close()
        if not location:
            raise Permanent(f"redirect with no Location from {url[:200]}")
        url = urljoin(url, location)
    raise Permanent(f"more than {MAX_REDIRECTS} redirects from {url[:200]}")


def read_capped(response: requests.Response, max_bytes: int = MAX_BODY_BYTES) -> bytes:
    """Read at most `max_bytes` + 1 and hang up.

    The extra byte is what makes "too large" detectable without reading the rest to find out
    how much larger. Requires a streamed response - `response.content` has already
    materialised the whole body by the time you could slice it.
    """
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(CHUNK_BYTES):
        chunks.append(chunk)
        size += len(chunk)
        if size > max_bytes:
            response.close()
            break
    return b"".join(chunks)[: max_bytes + 1]
