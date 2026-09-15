# News Intelligence Platform

Monitors Iranian news sources: crawl → deduplicate → classify → score impact → summarize →
publish a Persian analyst workbook, with a human review loop and an A/B lab feeding back
into prompt selection.

## Stack

Django + DRF + Postgres (pgvector) + Celery/Redis behind a Next.js App Router frontend.
TLS and static media are terminated by a shared Caddy edge on the VPS. Images are built by
CI, pushed to GHCR, and deployed with `docker compose`; nothing is built on the host.

```
backend/            Django project (config.settings.{base,dev,prod,test})
  core/             vocabulary, notify scoring, Persian text, error taxonomy
  sources/          the source registry, crawl strategies, extraction, prefilter
  articles/         Article/Image/Embedding storage, ingest, deduplication
  inference/        prompt variants, providers, budget guards, the three LLM nodes
  review/           human labelling queue and the blinded A/B pairing
  market/           TGJU price snapshots and the prediction back-test
  exports/          the Persian analyst workbook and the category text feeds
  api/              the read API and the three purpose-built dashboard documents

frontend/           Next.js 15, App Router, server components only
  app/              /, /article/[id], /review, /ab, /ops, /kpi, /market, /exports
  lib/api.js        the server-side Django client; the token never reaches the browser
  middleware.js     fail-closed login gate

deploy/             docker-compose for dev and prod, plus the Caddy site block
.github/workflows/  ci.yml (tests, lint, deploy checks) and deploy.yml (build → VPS)
```

## Setup

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # then fill in GAPGPT_API_KEY

docker compose -f ../deploy/docker-compose.dev.yml up -d   # postgres + redis
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_sources
.venv/bin/python manage.py seed_variants
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

```bash
cd frontend && npm ci && npm run dev      # http://localhost:3000
```

Credentials come from the environment only. There is no fallback default for any secret —
the pipeline this replaced shipped a live API key as an `os.getenv` default and it reached
a public git history. `config/settings/base.py` raises at import time on a missing one.

## Commands

```bash
python manage.py check --deploy --fail-level WARNING   # what CI runs against prod settings
python manage.py setup_schedule            # install the beat schedule (idempotent)
python manage.py check_provider            # which key is in effect, and does it have money
python manage.py seed_sources              # load sources/fixtures/sources.yaml (upsert)
python manage.py run_pipeline crawl        # queues to Celery; --now runs it inline
python manage.py run_pipeline inference --limit 20
python manage.py run_pipeline workbook     # --rebuild-all ignores the rolling window
python manage.py benchmark_models          # bake off candidate models on real articles
pytest                                     # offline; every provider call is mocked
ruff check .
```

Celery does the real work on a schedule; `run_pipeline` exists for the abnormal paths —
proving a fresh deployment, backfilling after an outage, and answering "is it the crawler
or the model?" without waiting for the next tick. `manage.py run_pipeline --help` lists
every stage.

The nightly workbook export only rebuilds days that could still have changed — a day can
only change if one of its articles was fetched inside the rolling window, because that is
the only set the inference cycle will re-answer. After a `manage.py import_legacy`, or on a
fresh deployment with an existing corpus, `run_pipeline workbook --rebuild-all` is the way
to produce the back catalogue once.

## Pages

UI chrome is English throughout; article title/lead/body are Persian and render RTL inline.

- **`/` Feed** — articles in the rolling window, filtered by category, source and notify
  status. The window is a query parameter, read fresh on every request.
- **`/article/[id]`** — one article with its latest classification, evaluation and summary,
  its duplicates, and the retrieved neighbours the model actually saw.
- **`/review`** — one article and a form pre-filled with the model's own answer, so a
  reviewer corrects rather than fills. Every approved row becomes truth for `/kpi`,
  few-shot examples for the next run, and part of the golden set.
- **`/ab`** — blinded pairwise judging between prompt variants, with the position-bias
  check reported alongside the standings. On a fresh deploy only the control variant is
  active; the A/B tab shows variant status and setup steps. Activate a second arm in Django
  admin when you are ready for the doubled inference cost — see `seed_variants`.
- **`/ops`** — the funnel, cost and tokens per day, node outcome rates, dead letters,
  prefilter effect, image status and per-source health.
- **`/kpi`** — model-vs-human agreement, the notify confusion matrix, and the market
  back-test.
- **`/market`** — gold and currency series with the scored prediction outcomes.
- **`/exports`** — the nightly workbooks and category feeds, downloadable behind login.

## Design notes

**Inference is append-only.** Classifications, evaluations and summaries are separate
tables carrying `prompt_version`, `provider`, `model` and the variant that produced them.
Re-running with a new prompt adds a row instead of overwriting, which is what makes A/B
comparison possible at all. Every read path resolves "latest" through a `DISTINCT ON`
subquery rather than by ordering in Python.

**An unassessed axis is NULL, never a sentinel.** Legacy substituted «خیلی کم» for score
axes its category-specific prompts never asked about, which made the notification floor
unreachable and silently suppressed *every* security and economics alert — 0 of 488
security articles, against 50.2% in production. `core/scoring.py` carries the regression
test, and "too few axes to decide" is its own status, distinct from "not notable".

**The notify rule has exactly one implementation.** `api/filters.py` filters by asking
`core.scoring.decide` for primary keys rather than re-expressing the rule as ORM `Case`
annotations. A second copy would drift the first time a threshold moved, and that drift is
the bug the rebuild exists to remove.

**Errors are classified, not caught.** `Transient` retries with exponential backoff,
`Permanent` dead-letters immediately, `Fatal` aborts the whole run through a Redis flag
every queued task checks at entry. A budget ceiling that only stops the task that noticed
it is not a ceiling. Retry lives in exactly one layer — the Celery task — because a second
loop inside the provider client compounds to nine HTTP calls for one logical inference.

**Budget guards are three different things.** `NEWS_RUN_BUDGET_USD` is the per-run money
ceiling and `NEWS_DAILY_BUDGET_USD` catches slow drift; both count the provider's own
reported usage. `NEWS_MAX_PROVIDER_CALLS_PER_RUN` is a runaway-loop breaker on request
*count*, which is what catches a retry storm that succeeds at nothing and therefore spends
nothing the money ceiling can see.

**Deduplication is tuned to precision, not recall.** Trigram Jaccard over folded titles. A
false positive silently drops a real story from the workbook; a false negative just prints
a duplicate row.

**Prompts are files, and the version is their hash.** `inference/prompt_texts/*.md` hold the
policy text; `prompt_version` is a sha256 of their contents, stamped on every row. A
hand-maintained version constant gets forgotten on exactly the edit you most need to trace.

**The workbook vocabulary is the team's, not ours.** Gold trend is `↑ ↓ خنثی نامطمئن` —
the only four values in 4,304 rows across all 40 workbooks the team produced, and the only
four the workbook's own dropdown accepts. Every vocabulary is declared once in
`core/vocabulary.py` and imported everywhere else.

**Exports are not media.** Caddy file-serves the whole media volume at `/media/*` with no
auth so images do not each occupy a gunicorn worker. Workbook filenames are deterministic,
so an export sitting on that volume would be downloadable by anyone who can guess one.
`EXPORT_DIR` is a separate volume, and `ExportDownloadView` — which requires a login — is
the only way in.

**The token never reaches the browser.** It lives in an httpOnly cookie, attached
server-side by `lib/api.js`. Middleware gates on the cookie's presence only, by listing
what is public rather than what is protected, so a page added later is protected by
default. The security boundary is Django, not the middleware.

## Deployment

`main` → CI → GHCR → VPS. `deploy.yml` builds both images tagged with the commit SHA,
writes those exact tags into `/opt/apps/news-intel/deploy/.env`, and runs `compose up -d`;
a one-shot `migrate` service runs migrations and `collectstatic` before anything serves.
Roll back by re-running the workflow with a previous SHA as the `tag` input.

## Backup and restore

The `backup` service dumps Postgres nightly into the `backups` volume, keeps 14 days, and
reads every archive data block with `pg_restore --file=/dev/null` before promoting it — an unreadable archive must not be published, and finding that out during an incident is the failure a backup
exists to prevent. `/ops` shows the age of the newest verified dump; anything over 36 hours
turns red there, because a backup job that stopped silently is otherwise indistinguishable
from one that is working.

The database is the only thing in the system that cannot be regenerated by re-running the
pipeline: articles could be re-crawled, but the human review labels could not.

```bash
cd /opt/apps/news-intel/deploy
docker compose -f docker-compose.prod.yml exec backup ls -lh /backups   # what exists
docker compose -f docker-compose.prod.yml logs --tail=50 backup         # why not, if empty
```

To restore, first rehearse on an isolated PostgreSQL instance. The commands below preserve
both the current database and the chosen dump. Stop the backup service as well as application
writers so it cannot connect while the database is renamed. Run this block from the deployment
directory; database credentials are expanded **inside** the container, not by the host shell.
Choose an unused recovery name if `newsintel_broken` already exists.

```bash
# 1. Stop writers and the dump job.
docker compose -f docker-compose.prod.yml stop backend worker-crawl worker-inference beat backup

# 2. Copy the chosen dump; replace this example filename with an existing archive.
docker compose -f docker-compose.prod.yml cp backup:/backups/newsintel-YYYYMMDD-HHMMSS.dump .

# 3. Preserve the current database, create a fresh one, and restore atomically.
# These SQL names match the default deployment; adjust all three for a custom database name.
docker compose -f docker-compose.prod.yml exec -T db sh -eu -c '
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
    -c "ALTER DATABASE newsintel RENAME TO newsintel_broken"
  createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" newsintel
'
docker compose -f docker-compose.prod.yml exec -T db sh -eu -c '
  pg_restore -U "$POSTGRES_USER" -d newsintel --no-owner --single-transaction --exit-on-error
' < newsintel-YYYYMMDD-HHMMSS.dump

# 4. Only after restore succeeds: inspect human review counts and representative records.
# Then restart. Do not run this step after any failed command above.
docker compose -f docker-compose.prod.yml up -d
```

`newsintel_broken` is deliberately left in place. Dropping it is a separate, deliberate
command once the restored database has been confirmed good — an automatic drop turns a
recoverable mistake into an unrecoverable one.

**The dumps live on the same host as the database.** That covers a dropped table, a bad
migration and a `docker volume rm dbdata`; it does not cover the disk dying. Copying the
`backups` volume off the box is the remaining piece of a real recovery story.

## History

The pre-Django pipeline (FastAPI, SQLite, a single-process CLI) was removed in favour of
this platform; its source is in git history and the four ~2,950-line scripts it in turn
replaced are archived outside the repository. `manage.py import_legacy` carries the old
SQLite corpus — articles, duplicate links and human review cases, but deliberately not its
machine labels — into Postgres.
