"""Test settings.

Required-secret defaults are injected BEFORE base is imported, because `base` raises on a
missing secret at import time by design. Every value here is obviously fake, so a test
settings module can never be mistaken for a deployable one.
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-real-secret")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_DB", "newsintel_test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
# A fake key: the provider refuses to construct without one, and every HTTP call in the
# suite is mocked. A REAL key here would mean one un-mocked test spends money silently.
os.environ.setdefault("GAPGPT_API_KEY", "test-key-not-real")
# Redis DB 15, never 0: the budget tests deliberately write and delete counter keys, and
# sharing a database with the dev environment would wipe a live run's ceiling.
os.environ.setdefault("REDIS_URL", "redis://localhost:56379/15")

from .base import *

DEBUG = False
# Tasks run inline; no broker is available in the test environment.
# Existing dispatch tests assume a closed circuit and no wallet HTTP.
NEWS_INFERENCE_PREFLIGHT = False
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BEAT_SCHEDULER = "celery.beat:PersistentScheduler"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# In-process cache for the throttle counters. The suite runs single-process, so this is a
# real shared counter here, and it means a throttle test cannot leave state in a Redis
# database that the NEXT run then starts inside. Tests that exercise a limit clear it
# explicitly; see api/tests/test_api.py.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
