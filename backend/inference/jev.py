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

# The eight locked investor topics. One line each, written so two topics rarely both fit:
# central-bank and data stories are macro_monetary, government economic rules are
# iran_economy_policy, and price moves themselves are markets_companies.
CATEGORIES = {
    "conflict_security": "Military action, attacks, security incidents, or armed conflict.",
    "sanctions_diplomacy": "Sanctions, nuclear talks, negotiations, or diplomatic relations.",
    "macro_monetary": (
        "Inflation, growth, employment, central-bank rates, liquidity, or economic data."
    ),
    "energy_commodities": (
        "Oil, gas, electricity, fuel, metals, or other commodity supply, prices, and policy."
    ),
    "iran_economy_policy": (
        "Iranian government economic decisions: budget, taxes, subsidies, price controls, "
        "trade or currency rules."
    ),
    "markets_companies": (
        "Moves in stock, currency, gold, or crypto markets; banks; or major company events."
    ),
    "disasters": "Earthquakes, floods, accidents, epidemics, or other disasters.",
    "social_unrest": "Protests, strikes, labour unrest, or civil disorder.",
    "other": "No material economic, financial, security, or geopolitical relevance.",
}

IMPACT = [
    "No plausible material effect.",
    "Low or indirect possible effect.",
    "Moderate possible effect for some participants.",
    "Large possible effect for a market or region.",
    "Exceptional possible effect across markets or Iran.",
]

# Three levels, not IMPACT's five: a tag only needs "central", "secondary" or "no".
WATCH_LEVELS = [
    "Not what this report is about.",
    "A secondary subject of this report.",
    "A main subject of this report.",
]
MAX_WATCH_TAGS = 5

# Asked only alongside `same_event`, so it costs one extra answer, not one extra call. It
# is read only when the report does merge; a missing fallback answer means "reports".
STANCES = {
    "reports": "Reports the occurrence without confirming or disputing earlier accounts.",
    "supports": "Confirms or corroborates facts the candidate already reported.",
    "contradicts": "Denies, disputes or contradicts facts the candidate reported.",
    "updates": "Adds a later development or corrects a figure, time or detail.",
}
OPTIONAL_ANSWERS = {"stance"}

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


def _questions(
    candidates: dict[str, str] | None,
    watch: dict[str, str] | None = None,
    multi: bool = False,
) -> dict:
    """The typed questions for one event.

    `watch` is the alias shortlist from core.watch. TypeSafe has no multi-label type, so it
    gets one three-level score question per shortlisted item (at most eight); the GapGPT
    fallback gets them as a single pick-up-to-five question, which costs one answer.
    """
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
        questions["stance"] = {
            "type": "choice",
            "instructions": (
                "If this report is the same occurrence as a candidate, how does it relate "
                "to that candidate's report? If it is not, answer reports."
            ),
            "criteria": STANCES,
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
    if watch and multi:
        questions["watch_items"] = {
            "type": "multi",
            "instructions": (
                f"Pick at most {MAX_WATCH_TAGS} items this report is substantively about; "
                "a passing mention does not count. Pick none if none fit."
            ),
            "criteria": watch,
        }
    elif watch:
        for slug, name in watch.items():
            questions[f"watch_{slug}"] = {
                "type": "score",
                "instructions": f"How central is {name} to this report?",
                "criteria": WATCH_LEVELS,
            }
    return questions


def watch_tags(answers: dict) -> list[str]:
    """Tagged watch-item slugs from either backend's answers, most central first."""
    if "watch_items" in answers:
        return list(answers["watch_items"].get("choices", []))[:MAX_WATCH_TAGS]
    scored = []
    for name, answer in answers.items():
        if not name.startswith("watch_"):
            continue
        try:
            level = float(answer["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if level >= 1:
            scored.append((-level, name.removeprefix("watch_")))
    return [slug for _, slug in sorted(scored)][:MAX_WATCH_TAGS]


def stance(answers: dict) -> tuple[str, float | None]:
    """The joining report's stance from either backend, defaulting to `reports`."""
    answer = answers.get("stance") or {}
    choice = answer.get("choice")
    if choice not in STANCES:
        return "reports", None
    try:
        confidence = float(answer.get("confidence", answer.get("probabilities", {}).get(choice)))
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None and not 0 <= confidence <= 1:
        confidence = None
    return choice, confidence


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
        if question["type"] == "multi" and item is None:
            answers[name] = {"type": "multi", "choices": [], "confidence": 0.0}
            continue
        if name in OPTIONAL_ANSWERS and (
            not isinstance(item, dict) or item.get("choice") not in question["criteria"]
        ):
            continue
        if not isinstance(item, dict):
            raise Permanent(f"fallback answer missing {name}")
        try:
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError) as exc:
            raise Permanent(f"fallback confidence for {name} is not a number") from exc
        confidence = min(max(confidence, 0.0), 1.0)
        if question["type"] == "multi":
            # Tags are optional extras: unknown keys are dropped rather than costing the
            # whole decision, but the answer must still be a list.
            picked = item.get("choices")
            if not isinstance(picked, list):
                raise Permanent(f"fallback choices for {name} are not a list")
            answers[name] = {
                "type": "multi",
                "choices": [key for key in picked if key in question["criteria"]][
                    :MAX_WATCH_TAGS
                ],
                "confidence": confidence,
            }
        elif question["type"] == "choice":
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
        elif question["type"] == "multi":
            spec[name] = {
                "question": question["instructions"],
                "choose_keys_from": question["criteria"],
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
                '{"score": <level integer>, "confidence": <0-1>}; for a question with '
                '"choose_keys_from" return {"choices": [<keys>], "confidence": <0-1>}. '
                "No other text."
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


def decide(
    state: dict,
    run_id: str,
    candidates: dict[str, str] | None = None,
    watch: dict[str, str] | None = None,
) -> dict:
    if settings.TYPESAFE_API_KEY:
        return _typesafe(state, _questions(candidates, watch), run_id)
    if settings.GAPGPT_API_KEY:
        return _gapgpt_decide(state, _questions(candidates, watch, multi=True), run_id)
    raise Fatal("no decision backend configured (TYPESAFE_API_KEY or GAPGPT_API_KEY)")


def brief(state: dict, run_id: str) -> dict:
    """Short attributed bilingual digest grounded in stored source evidence."""
    if not settings.GAPGPT_API_KEY:
        raise Fatal("GAPGPT_API_KEY is not configured")
    budget.check_optional()
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


def storyline_name(titles: list[str], run_id: str) -> dict:
    """A short neutral bilingual name for a storyline, from its first event headlines."""
    if not settings.GAPGPT_API_KEY:
        raise Fatal("GAPGPT_API_KEY is not configured")
    budget.check_optional()
    result, _ = _gapgpt(
        settings.NEWS_DECISION_FALLBACK_MODEL or settings.GAPGPT_MODEL,
        [
            {
                "role": "system",
                "content": (
                    "These headlines are consecutive reports of one developing situation. "
                    "Name the situation neutrally in at most six words in Persian and in "
                    "English, without dates, verdicts or forecasts. Return one JSON object "
                    'with string fields "name_fa" and "name_en".'
                ),
            },
            {"role": "user", "content": json.dumps(titles, ensure_ascii=False)},
        ],
        120,
        run_id,
        "storyline",
    )
    if not isinstance(result, dict) or not all(
        isinstance(result.get(key), str) and result[key].strip() for key in ("name_fa", "name_en")
    ):
        raise Permanent("storyline name did not match the expected schema")
    return {key: result[key].strip()[:120] for key in ("name_fa", "name_en")}


LANGUAGE_NAMES = {"fa": "Persian", "en": "English"}


def translate_title(title: str, language: str, run_id: str) -> tuple[str, str]:
    """One short headline translation into `language`; returns (title, model).

    Optional spend: it stops first under budget pressure (budget.check_optional).
    """
    if not settings.GAPGPT_API_KEY:
        raise Fatal("GAPGPT_API_KEY is not configured")
    budget.check_optional()
    result, usage = _gapgpt(
        settings.NEWS_DECISION_FALLBACK_MODEL or settings.GAPGPT_MODEL,
        [
            {
                "role": "system",
                "content": (
                    f"Translate this news headline into {LANGUAGE_NAMES[language]}. Keep "
                    "names, numbers and attribution; add nothing. Return one JSON object "
                    'with one string field "title".'
                ),
            },
            {"role": "user", "content": title[:400]},
        ],
        120,
        run_id,
        "title",
    )
    text = result.get("title") if isinstance(result, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise Permanent("title translation did not match the expected schema")
    return text.strip()[:300], usage.model
