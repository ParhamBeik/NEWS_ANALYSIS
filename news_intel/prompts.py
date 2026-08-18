"""Prompts for the news workflow.

The policy text lives in config/prompts/*.md so it can be tuned without touching code.
The version is derived from the content of those files, so editing a prompt automatically
changes the version stamped on every classification/evaluation/summary row - which is what
makes "did that prompt change help?" answerable instead of a guess.

Editing a prompt therefore does two things at once: it changes future output, and it marks
prior output as having come from a different prompt. Nothing is silently overwritten.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .core import config
from .sources import RawArticle

Level = Literal["خیلی کم", "کم", "متوسط", "زیاد", "خیلی زیاد"]
Category = Literal["security", "economics", "security/economics", "other"]
# Up / down / neutral / uncertain, in the workbook's own words. See EvaluationOutput.
GoldTrend = Literal["↑", "↓", "خنثی", "نامطمئن"]
GOLD_TRENDS: tuple[str, ...] = ("↑", "↓", "خنثی", "نامطمئن")


class ClassificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    confidence: Level
    rationale: str = Field(max_length=800)
    matched_economics_keywords: list[str] = Field(default_factory=list, max_length=12)
    matched_security_keywords: list[str] = Field(default_factory=list, max_length=12)


class EvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence_occurrence: Level
    gold_price_impact: Level | None = None
    security_relevance: Level | None = None
    # The vocabulary the team's own workbooks actually use: 4,304 rows across all 40
    # legacy outputs contain only these four values, and the workbook's data validation
    # on column I accepts only these four. "→" and "?" appear nowhere and would be
    # rejected by the dropdown an analyst clicks.
    gold_trend: GoldTrend | None = None
    rationale: str = Field(max_length=800)

    @model_validator(mode="after")
    def require_two_axes(self):
        if sum(value is not None for value in (
            self.confidence_occurrence, self.gold_price_impact, self.security_relevance
        )) < 2:
            raise ValueError("evaluation must assess at least two axes")
        return self


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    optimized_title: str = Field(min_length=1, max_length=300)
    one_line: str = Field(min_length=1, max_length=800)


@dataclass(frozen=True)
class ReviewedExample:
    category: str
    title: str
    output: str


# Fallbacks used only if config/prompts/ is missing, so an incomplete checkout still runs.
_DEFAULTS = {
    "classification": (
        "You classify Persian news for Iranian security and macroeconomic relevance.\n"
        "Return exactly one category: security, economics, security/economics, or other.\n"
        "Return only JSON matching the requested schema."
    ),
    "evaluation": (
        "You assess a classified Persian news article conservatively.\n"
        "Never fill an unassessed axis with a low or middle sentinel.\n"
        "Return only JSON matching the requested schema."
    ),
    "summary": (
        "Write one accurate Persian sentence for an operational news workbook.\n"
        "Return only JSON matching the requested schema."
    ),
}


def load_policy(name: str) -> str:
    path = config.PROMPTS_DIR / f"{name}.md"
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return _DEFAULTS[name]


def policies() -> dict[str, str]:
    return {name: load_policy(name) for name in _DEFAULTS}


def prompt_version() -> str:
    """Stable identifier for the current prompt set.

    A content hash rather than a hand-maintained constant: a hand-maintained one gets
    forgotten on exactly the edit you most need to trace.
    """
    combined = "\n---\n".join(f"{name}:{text}" for name, text in sorted(policies().items()))
    return "p" + hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]


CLASSIFICATION_POLICY = load_policy("classification")
EVALUATION_POLICY = load_policy("evaluation")
SUMMARY_POLICY = load_policy("summary")
PROMPT_VERSION = prompt_version()


def _article(article: RawArticle) -> dict[str, str]:
    return {
        "title": article.title,
        "lead": article.lead,
        "content": article.content[:6000],
        "source": article.original_outlet or article.source,
    }


def _examples(examples: Iterable[ReviewedExample]) -> list[dict[str, str]]:
    return [{"category": item.category, "title": item.title, "approved_output": item.output} for item in examples]


def classification_messages(article: RawArticle, examples: Iterable[ReviewedExample]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CLASSIFICATION_POLICY},
        {"role": "user", "content": json.dumps({
            "task": "Classify this article.",
            "reviewed_examples": _examples(examples),
            "article": _article(article),
            "json_schema": ClassificationOutput.model_json_schema(),
        }, ensure_ascii=False)},
    ]


def evaluation_messages(article: RawArticle, category: str, examples: Iterable[ReviewedExample]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": EVALUATION_POLICY},
        {"role": "user", "content": json.dumps({
            "task": "Evaluate this article.",
            "category": category,
            "reviewed_examples": _examples(examples),
            "article": _article(article),
            "json_schema": EvaluationOutput.model_json_schema(),
        }, ensure_ascii=False)},
    ]


def summary_messages(article: RawArticle, examples: Iterable[ReviewedExample]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SUMMARY_POLICY},
        {"role": "user", "content": json.dumps({
            "task": "Summarize this article.",
            "reviewed_examples": _examples(examples),
            "article": _article(article),
            "json_schema": SummaryOutput.model_json_schema(),
        }, ensure_ascii=False)},
    ]
