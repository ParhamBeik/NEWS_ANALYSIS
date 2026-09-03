"""Prompt text and the pydantic schemas the model must answer with.

Policy text lives in config/prompts/*.md so it can be tuned without touching code, and
`prompt_version` is a hash of that text - so editing a prompt both changes future output
and marks prior output as having come from a different prompt. A hand-maintained version
constant gets forgotten on exactly the edit you most need to trace.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import config
from .scoring import LEVELS
from .sources import RawArticle

Level = Literal["خیلی کم", "کم", "متوسط", "زیاد", "خیلی زیاد"]
Category = Literal["security", "economics", "security/economics", "other"]
# Up / down / neutral / uncertain, in the workbook's own words: the only four values in
# 4,304 rows across all 40 legacy workbooks, and the only four its dropdown accepts.
GoldTrend = Literal["↑", "↓", "خنثی", "نامطمئن"]

# The single source of these vocabularies, for storage, exports, KPI rows and the review
# form - so nothing can offer a value the schema would reject.
GOLD_TRENDS: tuple[str, ...] = GoldTrend.__args__
CATEGORIES: tuple[str, ...] = Category.__args__

assert set(Level.__args__) == set(LEVELS), "prompt Level must match the stored scale"


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
    gold_trend: GoldTrend | None = None
    rationale: str = Field(max_length=800)

    @model_validator(mode="after")
    def require_two_axes(self):
        assessed = (self.confidence_occurrence, self.gold_price_impact, self.security_relevance)
        if sum(value is not None for value in assessed) < 2:
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


# Used only if config/prompts/ is missing, so an incomplete checkout still runs.
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
# (output schema, instruction verb) per task. The verb is part of the prompt text the
# model sees, so it is spelled out rather than derived from the task name.
_TASKS = {
    "classification": (ClassificationOutput, "Classify"),
    "evaluation": (EvaluationOutput, "Evaluate"),
    "summary": (SummaryOutput, "Summarize"),
}


def load_policy(name: str) -> str:
    path = config.PROMPTS_DIR / f"{name}.md"
    if path.exists() and (text := path.read_text(encoding="utf-8").strip()):
        return text
    return _DEFAULTS[name]


def policies() -> dict[str, str]:
    return {name: load_policy(name) for name in _DEFAULTS}


def prompt_version() -> str:
    combined = "\n---\n".join(f"{name}:{text}" for name, text in sorted(policies().items()))
    return "p" + hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]


POLICIES = policies()
PROMPT_VERSION = prompt_version()


def messages(
    task: str, article: RawArticle, examples: Iterable[ReviewedExample], **extra
) -> list[dict[str, str]]:
    """The user turn is one JSON object: policy in the system turn, everything the model
    needs to answer - article, approved examples, output schema - in the user turn."""
    schema, verb = _TASKS[task]
    return [
        {"role": "system", "content": POLICIES[task]},
        {"role": "user", "content": json.dumps({
            "task": f"{verb} this article.",
            **extra,
            "reviewed_examples": [
                {"category": e.category, "title": e.title, "approved_output": e.output}
                for e in examples
            ],
            "article": {
                "title": article.title,
                "lead": article.lead,
                "content": article.content[:6000],
                "source": article.original_outlet or article.source,
            },
            "json_schema": schema.model_json_schema(),
        }, ensure_ascii=False)},
    ]
