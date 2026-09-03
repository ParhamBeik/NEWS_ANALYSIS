"""VPS settings. TLS is terminated by the shared Caddy edge, so the app trusts
X-Forwarded-Proto and must never be exposed on a port directly."""

from .base import *
from .base import ImproperlyConfigured, env_required  # noqa: F401

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = False  # Caddy already redirects; doing it twice loops.

# The ONE deploy warning this deployment answers differently, silenced by name and only by
# name. `check --deploy --fail-level WARNING` runs in CI with no fallback, so every other
# W00x fails the build; silencing the whole check instead of this single id - or wrapping
# the command in a `||` that falls back to a plain `check` - hides the next real one.
# security.W008 is SECURE_SSL_REDIRECT: the shared Caddy edge terminates TLS and already
# redirects, and doing it again behind the proxy is a loop.
SILENCED_SYSTEM_CHECKS = ["security.W008"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# Fail at boot rather than at the first paid call: a worker that starts without a key
# looks healthy and silently dead-letters every article it is handed.
GAPGPT_API_KEY = env_required("GAPGPT_API_KEY")
