import pytest

from news_intel.core import config


def test_load_dotenv_populates_missing_environment_only(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("GAPGPT_API_KEY=test-key\nEXISTING=from-file\n", encoding="utf-8")
    monkeypatch.delenv("GAPGPT_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING", "from-environment")

    config.load_dotenv(path)

    assert config.require_env("GAPGPT_API_KEY") == "test-key"
    assert config.env("EXISTING", "") == "from-environment"


def test_the_default_call_cap_clears_a_full_cycle(monkeypatch):
    """The cap is per run, not per article.

    A cycle of 25 articles issues up to 3 requests each. A cap below that aborts the run
    with a Fatal error, and run_loop stops the daemon on Fatal - so a "safety" default
    set too low silently ends the continuous fetching this system exists to do.
    """
    monkeypatch.delenv("NEWS_MAX_PROVIDER_CALLS", raising=False)
    assert config.provider_max_calls() >= 25 * 3


def test_a_non_positive_call_cap_is_refused(monkeypatch):
    monkeypatch.setenv("NEWS_MAX_PROVIDER_CALLS", "0")
    with pytest.raises(config.ConfigError):
        config.provider_max_calls()
