"""Prompt policy, output schemas, and message assembly.

FROZEN INVARIANT (3/4). Policy text lives in `inference/prompts/*.md` so it can be tuned
without touching code, and `prompt_version` is a sha256 of that text. Editing a prompt
therefore changes future output *and* marks prior output as having come from a different
prompt. A hand-maintained version constant gets forgotten on exactly the edit you most need
to trace.

The pydantic schemas are the contract with the model. They are also what makes an invalid
answer a `Permanent` error rather than a silently-stored wrong value: `Level | None` cannot
hold a made-up string, and `require_two_axes` refuses an evaluation that cannot decide.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.vocabulary import CATEGORIES, GOLD_TRENDS, LEVELS

# Mirrored from core.vocabulary as Literals, because pydantic needs them at type level and
# a mismatch must be a startup failure rather than a runtime rejection of every answer.
Level = Literal["خیلی کم", "کم", "متوسط", "زیاد", "خیلی زیاد"]
Category = Literal["security", "economics", "security/economics", "other"]
GoldTrend = Literal["↑", "↓", "خنثی", "نامطمئن"]

assert set(Level.__args__) == set(LEVELS), "prompt Level must match the stored scale"
assert set(Category.__args__) == set(CATEGORIES), "prompt Category must match storage"
assert set(GoldTrend.__args__) == set(GOLD_TRENDS), "prompt GoldTrend must match storage"


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
        assessed = (
            self.confidence_occurrence, self.gold_price_impact, self.security_relevance
        )
        if sum(value is not None for value in assessed) < 2:
            raise ValueError("evaluation must assess at least two axes")
        return self


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    optimized_title: str = Field(min_length=1, max_length=300)
    one_line: str = Field(min_length=1, max_length=800)


@dataclass(frozen=True)
class MemoryExample:
    """One retrieved neighbour: a past article and the verdict a human approved for it."""

    title: str
    category: str
    output: str
    similarity: float = 0.0
    reviewed: bool = True


# Used only if the policy directory is missing, so an incomplete checkout still runs.
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

# (output schema, instruction verb) per task. The verb is part of the prompt text the model
# sees, so it is spelled out rather than derived from the task name.
TASKS = {
    "classification": (ClassificationOutput, "Classify"),
    "evaluation": (EvaluationOutput, "Evaluate"),
    "summary": (SummaryOutput, "Summarize"),
}

# The node each task backs. Node names are what NodeEvent records and what /ops groups by.
TASK_FOR_NODE = {"classify": "classification", "evaluate": "evaluation", "summarize": "summary"}


def load_policy(name: str) -> str:
    path = settings.PROMPTS_DIR / f"{name}.md"
    if path.exists() and (text := path.read_text(encoding="utf-8").strip()):
        return text
    return _DEFAULTS[name]


@lru_cache(maxsize=1)
def policies() -> dict[str, str]:
    """Cached: read once per process. `reload_policies()` clears it after an edit."""
    return {name: load_policy(name) for name in _DEFAULTS}


def prompt_version() -> str:
    combined = "\n---\n".join(f"{name}:{text}" for name, text in sorted(policies().items()))
    return "p" + hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]


def reload_policies() -> None:
    policies.cache_clear()


def messages(
    task: str,
    *,
    title: str,
    lead: str,
    content: str,
    outlet: str,
    examples: Iterable[MemoryExample] = (),
    market: dict | None = None,
    **extra,
) -> list[dict[str, str]]:
    """Policy in the system turn; everything the model needs to answer in the user turn.

    One JSON object rather than prose, because the article text is Persian and the
    instructions are English - a delimiter the model cannot confuse with content matters
    more here than it would in a monolingual prompt.
    """
    schema, verb = TASKS[task]
    payload: dict = {
        "task": f"{verb} this article.",
        **extra,
        "article": {
            "title": title,
            "lead": lead,
            "content": (content or "")[:6000],
            "source": outlet,
        },
        "json_schema": schema.model_json_schema(),
    }
    if retrieved := [
        {
            "title": example.title,
            "category": example.category,
            "approved_output": example.output,
            "human_reviewed": example.reviewed,
        }
        for example in examples
    ]:
        # Named "similar_past_articles", not "examples": these are precedents from the same
        # desk, and labelling them as human-reviewed or not is what stops the model from
        # treating its own earlier guess as ground truth.
        payload["similar_past_articles"] = retrieved
    if market:
        payload["recent_market_context"] = market
    return [
        {"role": "system", "content": policies()[task]},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
