"""Paths and environment. Secrets come from the environment only, never a default."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Checked in: human-edited.
CONFIG_DIR = ROOT / "config"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"
PROMPTS_DIR = CONFIG_DIR / "prompts"
ROUTING_PATH = CONFIG_DIR / "routing.yaml"
WORKBOOK_TEMPLATE_PATH = CONFIG_DIR / "workbook_template.xlsx"

# Generated: everything the pipeline writes, so `rm -rf var/` is a full reset.
VAR_DIR = ROOT / "var"
OUTPUT_DIR = VAR_DIR / "outputs"
DB_PATH = VAR_DIR / "news.db"

TEHRAN_TZ = "Asia/Tehran"
DEFAULT_GAPGPT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_WINDOW_DAYS = "14"


class ConfigError(RuntimeError):
    """Missing or invalid configuration, raised at startup."""


def load_dotenv(path: Path | None = None) -> None:
    """Populate os.environ from .env. Existing env vars win.

    ponytail: six lines of stdlib instead of a python-dotenv dependency.
    """
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def require_env(name: str) -> str:
    value = env(name, "")
    if not value:
        raise ConfigError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


def _positive(name: str, default: float, cast) -> float:
    raw = env(name, str(default))
    try:
        value = cast(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be positive, got {value}")
    return value


def run_budget_usd() -> float:
    """Hard money ceiling per run, counted from the provider's reported usage."""
    return _positive("NEWS_RUN_BUDGET_USD", 1.00, float)


def provider_max_calls() -> int:
    """Runaway-loop breaker on request count per RUN, not per article.

    A cycle of 25 articles issues up to 75 requests, and hitting the cap is Fatal - which
    stops run-loop entirely. Set it well above any legitimate cycle; the money guard is
    run_budget_usd().
    """
    return int(_positive("NEWS_MAX_PROVIDER_CALLS", 500, int))


def provider_max_output_tokens() -> int:
    return int(_positive("NEWS_MAX_OUTPUT_TOKENS", 350, int))


def provider_token_prices() -> tuple[float, float]:
    """(input, output) dollars per million tokens. Resellers price differently upstream."""
    try:
        prices = (
            float(env("GAPGPT_INPUT_USD_PER_MILLION", "0.10")),
            float(env("GAPGPT_OUTPUT_USD_PER_MILLION", "0.40")),
        )
    except ValueError as exc:
        raise ConfigError("GAPGPT token prices must be numbers") from exc
    if min(prices) < 0:
        raise ConfigError("GAPGPT token prices cannot be negative")
    return prices


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
