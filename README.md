# News Intelligence Pipeline

Automated monitoring of Iranian news sources: crawl → deduplicate → classify → evaluate
impact → summarize → publish a Persian analyst workbook.

Replaces the legacy pipeline preserved under `LEGACY/` (four ~2,950-line near-identical
scripts, a 41 MB JSON re-serialized after every article, no tests, and no measurement of
whether any output was correct).

## Layout

```
news_intel/          the package
  core/              config, db, dag runtime, normalize, scoring
  sources.py         discovery + extraction, one RawArticle boundary
  dedupe.py          exact + near-duplicate merging
  providers.py       LLM boundary (GapGPT / Ollama / rule / fake)
  routing.py         which model answers which node
  prompts.py         prompt text + pydantic output schemas
  pipeline.py        ingest and inference orchestration
  reviews.py         human review queue, feeds few-shot examples
  metrics.py         model-vs-human agreement, drives /kpi
  evals.py           golden-set export + scoring
  exports.py         Excel / TXT / Markdown outputs
  dashboard.py       FastAPI: human review, KPIs, system health
  cli.py             entry point

config/              checked in, human-edited
  sources/*.yaml     one file per source
  prompts/*.md       policy text; editing one changes the prompt version
  routing.yaml       node -> provider/model
  workbook_template.xlsx

evals/golden.json    labelled cases
migrations/          one-shot legacy import
tests/               offline, no network, no API cost
var/                 ALL generated state (gitignored) - db, logs, outputs
LEGACY/              the old system, untouched, for reference
```

Modules are flat inside `news_intel/` on purpose. At 60–230 lines each, splitting them
into `sources/`, `llm/`, `nodes/` subpackages would add directories without adding
clarity — the failure mode this rebuild exists to correct.

`var/` holds everything the pipeline writes, so `rm -rf var/` is a full reset and
"mine vs generated" is obvious at a glance.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # then fill in GAPGPT_API_KEY
.venv/bin/python -m news_intel.cli init
```

Credentials come from the environment only. There is no fallback default for any secret —
the legacy pipeline shipped a live API key as an `os.getenv` default and it reached a
public git history.

## Commands

```bash
python -m news_intel.cli run --limit 20 --provider rule      # offline, free
python -m news_intel.cli run --limit 20 --provider gapgpt --export
python -m news_intel.cli run-loop --interval-minutes 30 --provider gapgpt --export
python -m news_intel.cli dedupe                              # report; --apply to link
python -m news_intel.cli canary                              # is each source still alive?
python -m news_intel.cli replay --node classify              # invalidate + recompute
python -m news_intel.cli review-queue --size 100             # build a labelling queue
python -m news_intel.cli review-import <path>                # ingest human labels
python -m news_intel.cli golden                              # approved reviews -> eval set
python -m news_intel.cli evaluate evals/golden.json --provider gapgpt
python -m news_intel.cli routes                              # which model answers what
python -m news_intel.cli compare --a-provider gapgpt --a-version <hash> \
                                  --b-provider gapgpt --b-version <hash>  # A/B: diffs two
                                                               # already-run prompt/provider
                                                               # variants into txt files
python -m news_intel.cli export
python -m news_intel.cli serve                               # dashboard on :8000
pytest                                                       # offline, no API cost
```

`--provider rule` runs the whole pipeline against a keyword baseline: no network, no cost.
Use it to verify wiring before spending anything. `--provider routed` reads
`config/routing.yaml`; any other value pins every node to that one provider.

## The review loop

The dashboard's main page is `/review`, not monitoring. It shows one article and a form
pre-filled with the model's own answer, so a reviewer corrects rather than fills. Every
approved row becomes three things at once:

1. truth for `/kpi` — accuracy, macro F1, per-axis MAE, notify precision/recall;
2. few-shot examples selected by title similarity (`reviews.reviewed_examples`);
3. the golden set, via `cli golden`.

`"ارزیابی نشد"` is a real choice on every axis. An axis nobody judged stays NULL through
all three of those paths — see the design note below for why that matters.

## Design notes

**Inference is append-only.** Classifications, evaluations and summaries are separate
tables carrying `prompt_version`, `provider` and `model`. Re-running with a new prompt adds
a row instead of overwriting, which is what makes A/B comparison and provider evaluation
possible at all.

**An unassessed axis is NULL, never a sentinel.** Legacy substituted `"خیلی کم"` for score
axes its category-specific prompts never asked about, which made the notification floor
unreachable and silently suppressed *every* security and economics alert — 0 of 488
security articles, against 50.2% in production. `core/scoring.py` and `tests/test_scoring.py`
carry the regression.

**Deduplication is tuned to precision, not recall.** Threshold 0.75 on trigram Jaccard,
measured against every title pair in the corpus. A false positive silently drops a real
story from the workbook; a false negative just prints a duplicate row. See the module
docstring in `dedupe.py` for the measurement.

**Errors are classified, not caught.** `Transient` retries with backoff, `Permanent`
dead-letters immediately, `Fatal` aborts the run. Legacy caught bare `Exception` and
retried everything forever — 465 articles were still being re-sent every 30 minutes.

**One source cannot fail the cycle.** Each source runs inside its own error boundary and a
failure marks it degraded and continues.

**Prompts are files, and the version is their hash.** `config/prompts/*.md` hold the policy
text; `prompt_version` is a sha256 of their contents, stamped on every row. Editing a prompt
therefore does two things at once — changes future output, and marks prior output as having
come from a different prompt. A hand-maintained version constant gets forgotten on exactly
the edit you most need to trace. `tests/test_prompts.py` asserts the policy text and the
pydantic schema agree on the permitted values, because they drifted once already.

**The workbook vocabulary is the team's, not ours.** Gold trend is `↑ ↓ خنثی نامطمئن` — the
only four values in 4,304 rows across all 40 workbooks the team produced, and the only four
the workbook's own dropdown accepts. The rebuild briefly emitted `→` and `?`, which Excel
would have rejected on entry.

**Nodes are routed independently.** `config/routing.yaml` maps each of `classify`,
`evaluate`, `summarize` to a provider and optionally a model, so moving to local inference
is partial and measurable: point `classify` at Ollama, read `/kpi`, then decide about the
next node. `evaluate` produces the scores that decide notifications, so it moves last.
Every inference row stores its own `provider` and `model`, and the "already done?" check is
keyed on them — swapping one node's model re-runs that node only.

**Budget guards are two different things.** `NEWS_RUN_BUDGET_USD` is the money ceiling,
counted from the provider's reported usage. `NEWS_MAX_PROVIDER_CALLS` is a runaway-loop
circuit breaker on request count and belongs well above a normal cycle — it was previously
defaulted to 3, which would abort any real run after three calls and, because the failure
is `Fatal`, stop `run-loop` entirely.
