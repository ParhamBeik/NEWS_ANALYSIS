"""Configuration and paths.

Secrets come from the environment only. There is deliberately no fallback default
for any credential: the legacy pipeline shipped a live API key as the `os.getenv`
default, which is how it ended up in a public git history.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Checked in: things a human edits.
CONFIG_DIR = ROOT / "config"
SOURCES_DIR = CONFIG_DIR / "sources"
PROMPTS_DIR = CONFIG_DIR / "prompts"
ROUTING_PATH = CONFIG_DIR / "routing.yaml"
WORKBOOK_TEMPLATE_PATH = CONFIG_DIR / "workbook_template.xlsx"
EVALS_DIR = ROOT / "evals"

# Generated: everything the pipeline writes. One gitignored root, so "mine" versus
# "generated" is obvious at a glance and the whole runtime state can be wiped with
# a single rm -rf var/.
VAR_DIR = ROOT / "var"
DATA_DIR = VAR_DIR
OUTPUT_DIR = VAR_DIR / "outputs"
LOG_DIR = VAR_DIR / "logs"

DB_PATH = VAR_DIR / "news.db"

TEHRAN_TZ = "Asia/Tehran"
DEFAULT_GAPGPT_MODEL = "gemini-2.5-flash-lite"


def load_dotenv(path: Path | None = None) -> None:
    """Populate os.environ from a .env file. Existing env vars win.

    ponytail: six lines of stdlib instead of a python-dotenv dependency.
    """
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


class ConfigError(RuntimeError):
    """Raised at startup for missing or invalid configuration."""


def require_env(name: str) -> str:
    """Return an env var or fail loudly. Never returns a default."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def run_budget_usd() -> float:
    raw = env("NEWS_RUN_BUDGET_USD", "1.00")
    try:
        budget = float(raw)
    except ValueError as exc:
        raise ConfigError(f"NEWS_RUN_BUDGET_USD must be a number, got {raw!r}") from exc
    if budget <= 0:
        raise ConfigError(f"NEWS_RUN_BUDGET_USD must be positive, got {budget}")
    return budget


def positive_int(name: str, default: int) -> int:
    raw = env(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be positive, got {value}")
    return value


def provider_max_calls() -> int:
    """Runaway circuit breaker: total provider requests one run may make.

    This is a *per run* ceiling, not a per article one. A cycle of 25 articles issues up
    to three requests each, so a low value here does not save money - it aborts the run
    with a Fatal error partway through, and `run-loop` stops the daemon on Fatal. The
    real money guard is NEWS_RUN_BUDGET_USD, which counts dollars the provider reports.
    This one exists only to stop an infinite retry loop, so it sits well above any
    legitimate cycle.
    """
    return positive_int("NEWS_MAX_PROVIDER_CALLS", 500)


def provider_max_output_tokens() -> int:
    return positive_int("NEWS_MAX_OUTPUT_TOKENS", 350)


def provider_token_prices() -> tuple[float, float]:
    """Configured dollar estimate per million tokens.

    Resellers can price differently from the upstream model; keep these values explicit
    in .env when the provider publishes its own tariff.
    """
    try:
        incoming = float(env("GAPGPT_INPUT_USD_PER_MILLION", "0.10"))
        outgoing = float(env("GAPGPT_OUTPUT_USD_PER_MILLION", "0.40"))
    except ValueError as exc:
        raise ConfigError("GAPGPT token prices must be numbers") from exc
    if incoming < 0 or outgoing < 0:
        raise ConfigError("GAPGPT token prices cannot be negative")
    return incoming, outgoing


def ensure_dirs() -> None:
    for directory in (DATA_DIR, OUTPUT_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
