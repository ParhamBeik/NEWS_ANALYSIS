"""VPS settings. TLS is terminated by the shared Caddy edge, so the app trusts
X-Forwarded-Proto and must never be exposed on a port directly."""

from .base import *  # noqa: F403
from .base import ImproperlyConfigured, env_required  # noqa: F401

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = False  # Caddy already redirects; doing it twice loops.
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
