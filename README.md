# News Intelligence Pipeline

Monitors Iranian news sources: crawl → deduplicate → classify → score impact → summarize →
publish a Persian analyst workbook.

## Stack

SQLite, `requests` + `BeautifulSoup`, `openpyxl`, `pydantic`, and FastAPI for the
dashboard. No server to run, no queue, no cache, no build step: the whole database is one
file under `var/`, and `rm -rf var/` is a full reset.

## Layout

```
news_intel/
  config.py      paths, .env loading, budget/limit settings
  db.py          schema, connections, settings table
  text.py        Persian normalization, hashing, date parsing
  scoring.py     the ordinal scale and the notify decision
  dag.py         node runtime: retry taxonomy, caching, cost ceiling
  sources.py     discovery, extraction, and history pagination -> RawArticle
  dedupe.py      exact + near-duplicate merging
  prompts.py     policy loading, output schemas, message assembly
  providers.py   the LLM boundary and per-node routing
  pipeline.py    quality gate, ingest, inference, rolling-window backfill
  reviews.py     review queue, few-shot examples, golden set, A/B diff
  metrics.py     model-vs-human agreement + operational telemetry
  exports.py     Excel workbook and text feeds
  dashboard.py   FastAPI: five pages
  cli.py         entry point

config/          checked in, human-edited
  sources.yaml   the sites to crawl
  routing.yaml   node -> provider/model
  prompts/*.md   policy text; editing one changes the prompt version
  golden.json    labelled eval cases
  workbook_template.xlsx

tests/           offline, no network, no API cost
var/             ALL generated state (gitignored) - db, outputs
```

Modules are flat on purpose. At 80-370 lines each, splitting them into subpackages would
add directories without adding clarity.

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
python -m news_intel.cli evaluate config/golden.json --provider gapgpt
python -m news_intel.cli routes                              # which model answers what
python -m news_intel.cli compare --a-provider gapgpt --a-version <hash> \
                                 --b-provider gapgpt --b-version <hash>
python -m news_intel.cli export
python -m news_intel.cli serve                               # dashboard on :8000
pytest                                                       # offline, no API cost
```

`--provider rule` runs the whole pipeline against a keyword baseline: no network, no cost.
Use it to verify wiring before spending anything. `--provider routed` reads
`config/routing.yaml`; any other value pins every node to that one provider.

## Dashboard

UI chrome is English throughout; article title/lead/body are Persian and render RTL inline.

- **`/` Home** — the notify feed: news that crossed the threshold within the rolling
  window. The window size is editable here and read fresh by every `run` cycle.
- **`/compare` A/B Diff** — read-only. Pick two already-run `(provider, model,
  prompt_version)` variants and see where they agreed or disagreed, article by article.
- **`/ops`** — cost/tokens per day, node outcome rates, fetch volume, the
  fetch→unique→classified→evaluated funnel, and per-source window coverage.
- **`/review`** — one article and a form pre-filled with the model's own answer, so a
  reviewer corrects rather than fills. Every approved row becomes three things at once:
  truth for `/kpi`, few-shot examples for the next run, and the golden set.
- **`/kpi` Quality** — model-vs-human agreement metrics.

## Design notes

**Inference is append-only.** Classifications, evaluations and summaries are separate
tables carrying `prompt_version`, `provider` and `model`. Re-running with a new prompt adds
a row instead of overwriting, which is what makes A/B comparison possible at all.

**An unassessed axis is NULL, never a sentinel.** Legacy substituted `"خیلی کم"` for score
axes its category-specific prompts never asked about, which made the notification floor
unreachable and silently suppressed *every* security and economics alert — 0 of 488
security articles, against 50.2% in production. `scoring.py` carries the regression test.

**Deduplication is tuned to precision, not recall.** Threshold 0.75 on trigram Jaccard,
measured against every title pair in the corpus. A false positive silently drops a real
story from the workbook; a false negative just prints a duplicate row. See the module
docstring in `dedupe.py`.

**Errors are classified, not caught.** `Transient` retries with backoff, `Permanent`
dead-letters immediately, `Fatal` aborts the run. Legacy caught bare `Exception` and
retried everything forever — 465 articles were still being re-sent every 30 minutes.
One source failing marks it degraded and the cycle continues.

**Prompts are files, and the version is their hash.** `config/prompts/*.md` hold the policy
text; `prompt_version` is a sha256 of their contents, stamped on every row. Editing a
prompt therefore changes future output *and* marks prior output as having come from a
different prompt. A hand-maintained version constant gets forgotten on exactly the edit you
most need to trace.

**The workbook vocabulary is the team's, not ours.** Gold trend is `↑ ↓ خنثی نامطمئن` —
the only four values in 4,304 rows across all 40 workbooks the team produced, and the only
four the workbook's own dropdown accepts. Every vocabulary (levels, categories, trends) is
declared once and imported everywhere else.

**Nodes are routed independently.** `config/routing.yaml` maps each of `classify`,
`evaluate`, `summarize` to a provider, so moving to local inference is partial and
measurable: point `classify` at Ollama, read `/kpi`, then decide about the next node.
`evaluate` produces the scores that decide notifications, so it moves last.

**Budget guards are two different things.** `NEWS_RUN_BUDGET_USD` is the money ceiling,
counted from the provider's reported usage. `NEWS_MAX_PROVIDER_CALLS` is a runaway-loop
circuit breaker on request count and belongs well above a normal cycle. A `fallback:`
provider in `routing.yaml` never overrides either — a budget error always aborts the run
rather than spending through a second provider.

**The rolling window heals itself, cheaply, when it's already whole.** Every `run` calls
`pipeline.ensure_window()`: one indexed query per source checks Jalali date coverage, and
the slow paginated backfill only runs when a real gap is found, with a 6-hour cooldown so a
structurally unfillable gap isn't re-attempted every cycle. Only khabarfoori and mehr have
a real history endpoint; shahrekhabar stays single-page and `/ops` says so honestly.
Backfilled articles always label on the free `rule` baseline, never the cycle's real
provider — a gap can mean hundreds of articles.

## History

The pipeline this replaced (four ~2,950-line near-identical scripts, a 41 MB JSON
re-serialized after every article, no tests) is archived outside the repo and its source
remains in git history before commit `0bfef06`. One-shot import migrations lived in
`migrations/` and are in history at the same point.
