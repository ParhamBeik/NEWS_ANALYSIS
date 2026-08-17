import pytest
from pydantic import ValidationError

from news_intel import prompts
from news_intel.core import db
from news_intel.prompts import (
    GOLD_TRENDS,
    EvaluationOutput,
    classification_messages,
    evaluation_messages,
    summary_messages,
)
from news_intel.sources import RawArticle

ARTICLE = RawArticle(source="test", url="https://test/1", title="خبر")


def test_classification_prompt_keeps_policy_separate_from_article_data():
    messages = classification_messages(ARTICLE, [])
    assert messages[0]["role"] == "system"
    assert "main meaning" in messages[0]["content"]
    assert "reviewed_examples" in messages[1]["content"]


def test_evaluation_requires_two_actual_axes():
    with pytest.raises(ValidationError):
        EvaluationOutput(confidence_occurrence="زیاد", rationale="one axis only")


# ------------------------------------------------- policy / schema coherence


def test_the_evaluation_policy_names_every_level_the_schema_accepts():
    """A policy that omits a level trains the model out of using it."""
    policy = prompts.load_policy("evaluation")
    missing = [level for level in db.LEVELS if level not in policy]
    assert not missing, f"evaluation.md never mentions {missing}"


def test_the_evaluation_policy_names_exactly_the_trend_values_the_schema_accepts():
    """The drift this guards against shipped once.

    The schema accepted «→» and «?» while every workbook the team produced used
    «خنثی» and «نامطمئن» — and the workbook's own dropdown rejected what the pipeline
    wrote. Policy text, schema, and workbook vocabulary have to move together.
    """
    policy = prompts.load_policy("evaluation")
    for trend in GOLD_TRENDS:
        assert trend in policy, f"evaluation.md never mentions {trend!r}"
    # "?" is ordinary punctuation in prose, so only the unambiguous symbol is checked.
    assert "→" not in policy


def test_every_gold_trend_value_validates_against_the_schema():
    for trend in GOLD_TRENDS:
        assert EvaluationOutput(
            confidence_occurrence="زیاد", gold_price_impact="کم",
            gold_trend=trend, rationale="ok",
        ).gold_trend == trend


def test_a_retired_trend_value_is_rejected():
    with pytest.raises(ValidationError):
        EvaluationOutput(confidence_occurrence="زیاد", gold_price_impact="کم",
                         gold_trend="→", rationale="ok")


def test_the_classification_policy_names_every_category_the_schema_accepts():
    policy = prompts.load_policy("classification")
    for category in ("security", "economics", "security/economics", "other"):
        assert category in policy


def test_the_policies_state_that_an_unassessed_axis_is_null():
    """The one instruction that prevents the legacy suppression bug from returning."""
    policy = prompts.load_policy("evaluation")
    assert "null" in policy
    assert "خیلی کم" in policy


# ---------------------------------------------------------------- versioning


def test_editing_a_policy_changes_the_prompt_version(tmp_path, monkeypatch):
    """Version is a content hash so a prompt edit is never silently untracked."""
    from news_intel.core import config

    monkeypatch.setattr(config, "PROMPTS_DIR", tmp_path)
    for name in ("classification", "evaluation", "summary"):
        (tmp_path / f"{name}.md").write_text("original", encoding="utf-8")
    before = prompts.prompt_version()

    (tmp_path / "evaluation.md").write_text("original, plus one clarification", encoding="utf-8")
    assert prompts.prompt_version() != before


def test_the_shipped_policies_are_the_ones_that_get_sent():
    """Guards against the fallback defaults silently standing in for the real files."""
    system = evaluation_messages(ARTICLE, "security", [])[0]["content"]
    assert system == prompts.load_policy("evaluation")
    assert len(system) > len(prompts._DEFAULTS["evaluation"])


def test_each_task_sends_its_own_policy():
    assert classification_messages(ARTICLE, [])[0]["content"] != \
        summary_messages(ARTICLE, [])[0]["content"]


def test_article_text_is_truncated_before_it_reaches_the_provider():
    long_article = RawArticle(source="test", url="https://test/1", title="خبر", content="ب" * 20_000)
    assert len(summary_messages(long_article, [])[1]["content"]) < 12_000
