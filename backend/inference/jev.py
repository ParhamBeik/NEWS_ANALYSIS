"""Bounded news judgments (Jev) and attributed briefs.

Two decision backends return the same answer shape, so the pipeline never branches on them:

- TypeSafe Jev, called directly at `api.typesafe.ai`. OpenRouter also serves Jev but
  answers the Tehran server with "Access denied by security policy", so it is not used.
- A GapGPT fallback that asks a cheap model for the same typed answers while no TypeSafe
  key is configured. Its confidences are self-reported, not calibrated; usage rows carry
  the provider so the two can be compared before thresholds are trusted.

Briefs are prose, which Jev does not write, and always go to GapGPT.
"""

from __future__ import annotations

import json

import requests
from django.conf import settings

from core.errors import BudgetExceeded, Fatal, Permanent, Transient

from . import budget
from .models import AIUsageRecord

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

BRIEF_FIELDS = (
    "title_fa",
    "title_en",
    "brief_fa",
    "brief_en",
    "channels_fa",
    "channels_en",
    "uncertainty_fa",
    "uncertainty_en",
)

BRIEF_INSTRUCTIONS = (
    "Use only the provided source evidence. Write factual English and Persian briefs (at "
    "most two sentences each), plus English and Persian titles. Attribute the reported facts "
    "to the named sources. Describe one possible economic or geopolitical transmission "
    "channel in each language, clearly as a possibility. State any material uncertainty in "
    "each language, or say evidence is limited. Never forecast, advise, invent facts, or "
    "claim news caused a market move. Return one JSON object with exactly these string "
    "fields: " + ", ".join(BRIEF_FIELDS) + "."
)


def configured() -> bool:
    """Whether any decision backend can run."""
    return bool(settings.TYPESAFE_API_KEY or settings.GAPGPT_API_KEY)


def backend_name() -> str:
    return "typesafe" if settings.TYPESAFE_API_KEY else "gapgpt"


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


def _questions(candidates: dict[str, str] | None) -> dict:
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
    return questions


# ---------------------------------------------------------------------- TypeSafe


def _typesafe(state: dict, questions: dict, run_id: str) -> dict:
    budget.check(run_id)
    budget.reserve_call(run_id)
    try:
        try:
            response = requests.post(
                settings.TYPESAFE_BASE_URL.rstrip("/") + "/systemone",
                json={"model": settings.TYPESAFE_JEV_MODEL, "state": state, "questions": questions},
                headers={"Authorization": f"Bearer {settings.TYPESAFE_API_KEY}"},
                timeout=25,
            )
        except requests.RequestException as exc:
            raise Transient("TypeSafe network request failed") from exc
        status = response.status_code
        if status == 402:
            raise BudgetExceeded("TypeSafe credits exhausted")
        if status in {429, 500, 502, 503, 524, 529}:
            raise Transient(f"TypeSafe returned {status}")
        if status in {401, 403}:
            raise Fatal(f"TypeSafe authentication returned {status}")
        if not response.ok:
            raise Permanent(f"TypeSafe returned {status}: {response.text[:200]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise Transient("TypeSafe returned invalid JSON") from exc
    except Exception:
        budget.release_call(run_id)
        raise
    usage = data.get("usage") or {}
    tokens_in = int(usage.get("input_tokens") or 0)
    consumed = budget.Usage(
        tokens_in=tokens_in,
        tokens_out=int(usage.get("output_tokens") or 0),
        # TypeSafe reports tokens, not money; output is free on its price list.
        cost_usd=tokens_in * settings.TYPESAFE_INPUT_USD_PER_MILLION / 1_000_000,
        provider="TypeSafe",
        model=str(data.get("model") or settings.TYPESAFE_JEV_MODEL),
    )
    budget.charge(run_id, consumed)
    _record_usage("jev", run_id, consumed)
    if not isinstance(data.get("answers"), dict):
        raise Transient("TypeSafe response has no answers")
    return data


# ---------------------------------------------------------------------- GapGPT


def _gapgpt(
    model: str,
    messages: list[dict],
    max_tokens: int,
    run_id: str,
    stage: str,
    prices: tuple[float, float] = (0.0, 0.0),
):
    from .providers import GapGPTProvider

    provider = GapGPTProvider(model=model, token_prices=prices)
    body = provider._post(
        "chat/completions",
        {
            "model": provider.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        },
        run_id,
    )
    usage = provider._usage(body)
    budget.charge(run_id, usage)
    _record_usage(stage, run_id, usage)
    try:
        choice = body["choices"][0]
        if choice.get("finish_reason") == "length":
            raise Permanent(f"GapGPT {stage} output truncated at {max_tokens} tokens")
        return json.loads(choice["message"]["content"]), usage
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise Permanent(f"GapGPT {stage} returned malformed JSON") from exc


def _fallback_answers(raw: dict, questions: dict) -> dict:
    """Translate the fallback model's JSON into Jev's answer shape, rejecting anything off-scale."""
    answers = {}
    for name, question in questions.items():
        item = raw.get(name)
        if not isinstance(item, dict):
            raise Permanent(f"fallback answer missing {name}")
        try:
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError) as exc:
            raise Permanent(f"fallback confidence for {name} is not a number") from exc
        confidence = min(max(confidence, 0.0), 1.0)
        if question["type"] == "choice":
            choice = item.get("choice")
            if choice not in question["criteria"]:
                raise Permanent(f"fallback choice for {name} is outside the criteria")
            answers[name] = {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {choice: confidence},
            }
        else:
            try:
                level = int(item.get("score"))
            except (TypeError, ValueError) as exc:
                raise Permanent(f"fallback score for {name} is not an integer") from exc
            if not 0 <= level < len(question["criteria"]):
                raise Permanent(f"fallback score for {name} is out of range")
            answers[name] = {"type": "score", "score": float(level), "confidence": confidence}
    return answers


def _gapgpt_decide(state: dict, questions: dict, run_id: str) -> dict:
    spec = {}
    for name, question in questions.items():
        if question["type"] == "choice":
            spec[name] = {
                "question": question["instructions"],
                "choose_one_key_from": question["criteria"],
            }
        else:
            spec[name] = {
                "question": question["instructions"],
                "levels": {str(i): text for i, text in enumerate(question["criteria"])},
            }
    messages = [
        {
            "role": "system",
            "content": (
                "You classify one news report. Answer every question from the evidence only. "
                "Return one JSON object keyed by question id. For a choice question return "
                '{"choice": <one key>, "confidence": <0-1>}; for a levelled question return '
                '{"score": <level integer>, "confidence": <0-1>}. No other text.'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"report": state, "questions": spec}, ensure_ascii=False, default=str
            ),
        },
    ]
    raw, usage = _gapgpt(
        settings.NEWS_DECISION_FALLBACK_MODEL or settings.GAPGPT_MODEL,
        messages,
        settings.NEWS_DECISION_MAX_TOKENS,
        run_id,
        "jev",
    )
    return {"model": f"gapgpt:{usage.model}", "answers": _fallback_answers(raw, questions)}


# ---------------------------------------------------------------------- public API


def decide(state: dict, run_id: str, candidates: dict[str, str] | None = None) -> dict:
    questions = _questions(candidates)
    if settings.TYPESAFE_API_KEY:
        return _typesafe(state, questions, run_id)
    if settings.GAPGPT_API_KEY:
        return _gapgpt_decide(state, questions, run_id)
    raise Fatal("no decision backend configured (TYPESAFE_API_KEY or GAPGPT_API_KEY)")


def brief(state: dict, run_id: str) -> dict:
    """Short attributed bilingual digest grounded in stored source evidence."""
    if not settings.GAPGPT_API_KEY:
        raise Fatal("GAPGPT_API_KEY is not configured")
    result, _ = _gapgpt(
        settings.NEWS_BRIEF_MODEL,
        [
            {"role": "system", "content": BRIEF_INSTRUCTIONS},
            {"role": "user", "content": json.dumps(state, ensure_ascii=False, default=str)},
        ],
        settings.NEWS_BRIEF_MAX_TOKENS,
        run_id,
        "brief",
        (settings.NEWS_BRIEF_INPUT_USD_PER_MILLION, settings.NEWS_BRIEF_OUTPUT_USD_PER_MILLION),
    )
    if not isinstance(result, dict) or any(
        not isinstance(result.get(name), str) for name in BRIEF_FIELDS
    ):
        raise Transient("brief did not match the expected schema")
    return {name: result[name] for name in BRIEF_FIELDS}
