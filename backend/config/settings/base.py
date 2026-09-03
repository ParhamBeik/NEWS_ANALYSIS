"""Settings shared by every environment.

Secrets have no defaults. `env_required` raises at import time rather than letting the
process boot with a placeholder credential - the legacy pipeline shipped a live API key as
an `os.getenv` default and it reached a public git history.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


class ImproperlyConfigured(RuntimeError):
    """A required setting is missing or unparseable. Raised during startup, on purpose."""


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file. Existing environment wins.

    Six lines of stdlib instead of a python-dotenv dependency. Existing-wins ordering is
    what lets the same settings module serve local development (file) and the VPS
    (compose env_file plus real environment) without a branch.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def env_required(name: str) -> str:
    if value := env(name):
        return value
    raise ImproperlyConfigured(f"{name} is not set")


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer") from exc


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a number") from exc


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


# --------------------------------------------------------------------------- django core

SECRET_KEY = env_required("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework.authtoken",
    "rest_framework",
    "corsheaders",
    "django_filters",
    "django_celery_beat",
    "core",
    "sources",
    "articles",
    "inference",
    "review",
    "market",
    "exports",
    "api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "newsintel"),
        "USER": env("POSTGRES_USER", "newsintel"),
        "PASSWORD": env_required("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 60),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# The pipeline reasons in Tehran local time because the workbook groups by Jalali day, but
# storage stays UTC - converting once at the display boundary is the only way to keep a
# rolling window honest across DST and timezone changes.
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
TEHRAN_TZ = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))

# ----------------------------------------------------------------------------- rest api

REST_FRAMEWORK = {
    # The whole product is behind one login; an endpoint that forgets to declare a
    # permission class must fail closed, not serve the corpus to the internet.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 30,
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# ------------------------------------------------------------------------------- celery

CELERY_BROKER_URL = env("REDIS_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ACKS_LATE = True
# A crawl worker killed mid-fetch must not have its task silently dropped, and an
# inference task must never be handed to a second worker while the first still holds it.
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = env_int("CELERY_TASK_TIME_LIMIT", 900)
CELERY_TASK_SOFT_TIME_LIMIT = env_int("CELERY_TASK_SOFT_TIME_LIMIT", 840)
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TIMEZONE = "UTC"

REDIS_URL = CELERY_BROKER_URL

# ---------------------------------------------------------------------- pipeline config

# Money guard, counted from the provider's own reported usage. Two ceilings, because they
# fail differently: a single runaway run and a slow drift over a day.
NEWS_RUN_BUDGET_USD = env_float("NEWS_RUN_BUDGET_USD", 1.00)
NEWS_DAILY_BUDGET_USD = env_float("NEWS_DAILY_BUDGET_USD", 3.00)
# Runaway-loop breaker on request COUNT, not money. Belongs well above a normal cycle.
NEWS_MAX_PROVIDER_CALLS_PER_RUN = env_int("NEWS_MAX_PROVIDER_CALLS_PER_RUN", 1000)
# 350 is enough for every node's JSON (the winner uses 234) and is a real selection
# criterion, not just a cost guard: it excludes models that spend their output budget on
# internal reasoning tokens before emitting anything. gpt-5-nano produced NO content even
# at 2000; gemini-3.5-flash needed ~240 reasoning tokens before its answer and so was
# truncated here. GapGPT also pre-reserves the full max_tokens cost per request, so this
# number is charged whether or not it is used.
NEWS_MAX_OUTPUT_TOKENS = env_int("NEWS_MAX_OUTPUT_TOKENS", 350)
NEWS_ROLLING_WINDOW_DAYS = env_int("NEWS_ROLLING_WINDOW_DAYS", 14)
NEWS_CRAWL_LIMIT_PER_SOURCE = env_int("NEWS_CRAWL_LIMIT_PER_SOURCE", 40)
NEWS_HTTP_TIMEOUT = env_int("NEWS_HTTP_TIMEOUT", 20)
NEWS_USER_AGENT = env(
    "NEWS_USER_AGENT", "news-intel/2.0 (+research pipeline; contact via site)"
)

GAPGPT_API_KEY = env("GAPGPT_API_KEY")
GAPGPT_BASE_URL = env("GAPGPT_BASE_URL", "https://api.gapgpt.app/v1")
# Chosen by `benchmark_models` over 60 real Persian articles, not by assertion: 97.1%
# schema compliance against 80.3% for gemini-2.5-flash-lite, at $0.000175/article and
# p95 2.8s. Re-run the command to challenge it.
GAPGPT_MODEL = env("GAPGPT_MODEL", "gemini-3.1-flash-lite")
GAPGPT_EMBEDDING_MODEL = env("GAPGPT_EMBEDDING_MODEL", "text-embedding-3-small")
GAPGPT_EMBEDDING_DIM = env_int("GAPGPT_EMBEDDING_DIM", 1536)
# Fallback pricing, used only when the provider does not report cost on a response.
GAPGPT_INPUT_USD_PER_MILLION = env_float("GAPGPT_INPUT_USD_PER_MILLION", 0.10)
GAPGPT_OUTPUT_USD_PER_MILLION = env_float("GAPGPT_OUTPUT_USD_PER_MILLION", 0.40)

PROMPTS_DIR = BASE_DIR / "inference" / "prompts"
WORKBOOK_TEMPLATE_PATH = BASE_DIR / "exports" / "assets" / "workbook_template.xlsx"
EXPORT_DIR = Path(env("EXPORT_DIR", str(BASE_DIR / "media" / "exports")))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}
