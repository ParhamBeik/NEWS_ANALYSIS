"""OpenRouter Decisions API adapter for bounded news judgments."""

from __future__ import annotations

import requests
from django.conf import settings

from core.errors import BudgetExceeded, Fatal, Permanent, Transient

from . import budget
from .models import AIUsageRecord

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

CATEGORIES = {
    "monetary": "Central-bank rates, liquidity, or monetary policy.",
    "macro": "Inflation, employment, growth, fiscal policy, or economic data.",
    "sanctions_trade": "Sanctions, trade restrictions, tariffs, imports, or exports.",
    "geopolitics": "Diplomacy, conflict, or political decisions with economic channels.",
    "energy": "Oil, gas, electricity, or energy supply and policy.",
    "markets": "Financial market structure, banking, or major corporate events.",
    "other": "No material economic, financial, or geopolitical relevance.",
}

IMPACT = [
    "No plausible material effect.",
    "Low or indirect possible effect.",
    "Moderate possible effect for some participants.",
    "Large possible effect for a market or region.",
    "Exceptional possible effect across markets or Iran.",
]


def _record_usage(stage: str, run_id: str, usage: budget.Usage) -> None:
    event_id = int(run_id.removeprefix("event-")) if run_id.startswith("event-") else None
    AIUsageRecord.objects.create(
        event_id=event_id,
        stage=stage,
        provider=usage.provider,
        model=usage.model,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        cost_usd=usage.cost_usd,
    )


def _request(url: str, payload: dict) -> dict:
    if not settings.OPENROUTER_API_KEY:
        raise Fatal("OPENROUTER_API_KEY is not configured")
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
            timeout=25,
        )
    except requests.RequestException as exc:
        raise Transient("OpenRouter network request failed") from exc
    if response.status_code == 402:
        raise BudgetExceeded("OpenRouter credits exhausted")
    if response.status_code in {429, 500, 502, 503, 524, 529}:
        raise Transient(f"OpenRouter returned {response.status_code}")
    if response.status_code in {401, 403}:
        raise Fatal(f"OpenRouter authentication returned {response.status_code}")
    if not response.ok:
        raise Permanent(f"OpenRouter returned {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise Transient("OpenRouter returned invalid JSON") from exc


def decide(state: dict, run_id: str, candidates: dict[str, str] | None = None) -> dict:
    questions = {
        "category": {
            "type": "choice",
            "instructions": "Choose the main news topic.",
            "criteria": CATEGORIES,
        },
        "iran": {
            "type": "score",
            "instructions": (
                "Potential significance for Iranian investors and Iran's economy, "
                "without claiming a price direction."
            ),
            "criteria": IMPACT,
        },
        "global": {
            "type": "score",
            "instructions": (
                "Potential global economic or geopolitical significance, "
                "without claiming a price direction."
            ),
            "criteria": IMPACT,
        },
    }
    if candidates:
        questions["same_event"] = {
            "type": "choice",
            "instructions": (
                "Does this report describe the same concrete occurrence as one candidate? "
                "Similar topics or people alone are not enough."
            ),
            "criteria": {
                "none": "A distinct occurrence or insufficient evidence to merge.",
                **candidates,
            },
        }
    for key, description in {
        "fx": "Iranian foreign exchange rates",
        "gold": "Iranian gold and coins",
        "tehran_index": "the Tehran equity index",
        "oil": "oil prices",
        "bitcoin": "Bitcoin",
    }.items():
        questions[f"asset_{key}"] = {
            "type": "score",
            "instructions": (
                f"Potential relevance to {description}; do not infer a realized price move."
            ),
            "criteria": IMPACT,
        }
    budget.check(run_id)
    budget.reserve_call(run_id)
    try:
        data = _request(
            DECISIONS_URL,
            {
                "model": settings.OPENROUTER_JEV_MODEL,
                "state": state,
                "questions": questions,
            },
        )
    except Exception:
        budget.release_call(run_id)
        raise
    usage = data.get("usage") or {}
    consumed = budget.Usage(
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
        cost_usd=float(usage.get("cost") or 0),
        provider="OpenRouter",
        model=str(data.get("model") or settings.OPENROUTER_JEV_MODEL),
    )
    budget.charge(run_id, consumed)
    _record_usage("jev", run_id, consumed)
    if not isinstance(data.get("answers"), dict):
        raise Transient("OpenRouter Decisions response has no answers")
    return data


def brief(state: dict, run_id: str) -> dict:
    """Short attributed bilingual digest grounded in stored source evidence."""
    budget.check(run_id)
    budget.reserve_call(run_id)
    try:
        data = _request(
            CHAT_URL,
            {
                "model": settings.OPENROUTER_BRIEF_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Use only the provided source evidence. Write factual English and "
                            "Persian briefs (at most two sentences each), plus English and "
                            "Persian titles. "
                            "Attribute the reported facts to the named sources. Describe one "
                            "possible economic or geopolitical transmission channel in each "
                            "language, clearly as a possibility. State any material uncertainty "
                            "in each language, or say evidence is limited. Never forecast, "
                            "advise, "
                            "invent facts, or claim news caused a market move. Return the "
                            "requested "
                            "JSON fields."
                        ),
                    },
                    {"role": "user", "content": str(state)},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "news_brief",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                    "title_fa": {"type": "string"},
                                    "title_en": {"type": "string"},
                                "brief_fa": {"type": "string"},
                                "brief_en": {"type": "string"},
                                "channels_fa": {"type": "string"},
                                "channels_en": {"type": "string"},
                                "uncertainty_fa": {"type": "string"},
                                "uncertainty_en": {"type": "string"},
                            },
                            "required": [
                                    "title_fa",
                                    "title_en",
                                "brief_fa",
                                "brief_en",
                                "channels_fa",
                                "channels_en",
                                "uncertainty_fa",
                                "uncertainty_en",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
            },
        )
    except Exception:
        budget.release_call(run_id)
        raise
    usage = data.get("usage") or {}
    consumed = budget.Usage(
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
        cost_usd=float(usage.get("cost") or 0),
        provider="OpenRouter",
        model=str(data.get("model") or settings.OPENROUTER_BRIEF_MODEL),
    )
    budget.charge(run_id, consumed)
    _record_usage("brief", run_id, consumed)
    try:
        import json

        result = json.loads(data["choices"][0]["message"]["content"])
        fields = (
            "title_fa",
            "title_en",
            "brief_fa",
            "brief_en",
            "channels_fa",
            "channels_en",
            "uncertainty_fa",
            "uncertainty_en",
        )
        if any(not isinstance(result[name], str) for name in fields):
            raise ValueError("non-string brief field")
        return {name: result[name] for name in fields}
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise Transient("OpenRouter brief did not match the expected schema") from exc
