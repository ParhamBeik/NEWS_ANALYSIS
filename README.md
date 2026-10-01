# News Intelligence

News Intelligence crawls Iranian news sources, deduplicates articles, classifies and scores
them with LLMs, supports human review and A/B prompt evaluation, and publishes Persian analyst
workbooks.

## Directory map

```text
backend/                 Django + DRF + Celery application
  config/                settings, URLs, ASGI/WSGI, Celery
  core/                  shared scoring, text, vocabulary, errors, CLI commands
  sources/               source registry, crawlers, extraction, prefilter
  articles/              article/image/embedding storage, ingest, deduplication
  inference/             prompts, providers, budgets, circuits, inference tasks
  review/                human labels and blinded A/B comparisons
  market/                TGJU prices and prediction backtests
  exports/               Persian workbooks and category feeds
  api/                   authenticated read API
frontend/                Next.js App Router dashboard
deploy/                  Docker Compose, Caddy, backup, and release checks
.github/workflows/       CI and deployment workflows
backend/inference/prompt_texts/
                          runtime prompt policy files, versioned by content hash
```

Generated folders such as `backend/.venv`, `frontend/node_modules`, `frontend/.next`, caches,
and `graphify-out` are local build or analysis output and are not source files.

## Runtime flow

```text
sources → articles → inference → review/market → exports/api → frontend
             PostgreSQL/pgvector stores data; Redis/Celery runs background work.
```

`ARCHITECTURE.md` explains dependency layers and invariants. `AGENTS.md` contains contributor
rules and the minimum checks. The three Markdown files under `backend/inference/prompt_texts/`
are loaded by the application and must be treated as runtime policy, not documentation.

## Setup

Requirements: `uv`, Python 3.13, Node 24, and Docker.

```bash
make setup
make services
backend/.venv/bin/python backend/manage.py migrate
make dev
```

Set the required provider and database values in `backend/.env`; secrets are environment-only.
`make help` lists everything. `make ci` runs local lint, Django/deploy checks, migration
drift, both test suites and the frontend build. GitHub CI also runs dependency audits,
both Docker image builds. `main` deploys after successful CI.

## Useful commands

```bash
make test       # backend and frontend tests
make lint       # Ruff
make check      # Django and deployment checks
make migrations # migration drift check
make build      # production frontend build
make ci         # all local CI gates
```

From `backend/`, operator commands include `manage.py run_pipeline`, `setup_schedule`,
`seed_sources`, `seed_variants`, `check_provider`, and `benchmark_models`.

## Dashboard routes

`/` feed · `/article/[id]` detail · `/review` human review · `/ab` prompt lab · `/ops` health
and cost · `/kpi` quality · `/market` prices and backtests · `/exports` workbooks.

## Deployment and backups

CI builds backend and frontend images, publishes them to GHCR, and the deploy workflow updates
the VPS Compose stack after successful CI. `deploy/check-stack.sh` is the read-only release gate.

- `deploy/backup.sh`: creates verified PostgreSQL custom-format dumps and retains recent files.
- `deploy/copy-backup.sh`: copies a verified dump to an always-on SSH destination.
- `deploy/pull-backup.sh`: pulls and verifies a dump on the FileVault Mac before promotion.
- `deploy/docker-compose.*.yml`: local and production service definitions.

The backup scripts write temporary files and promote them only after checksum or archive
verification. Run `backend/.venv/bin/python -m unittest discover -s deploy/tests -v` after
changing them.

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
The deploy job runs on the Mac's `newsintel-mac` GitHub runner, installed under
`~/.local/share/newsintel-runner` as a user LaunchAgent. GitHub-hosted runners cannot
reach the VPS's SSH port, and the VPS runner could not reliably report job results
back to GitHub. CI and image builds still use GitHub-hosted runners. Keep the Mac
awake and online for deployment; otherwise the job queues until the runner returns.
This Mac account holds the VPS SSH key, so keep the deploy workflow restricted to
reviewed `main`.

**Nothing deploys unless CI passed.** Deploy triggers on CI's completion, not on the push,
and builds the exact commit CI tested — so a second push while CI is running cannot ship
code no test ever saw. A red CI means no deploy at all; the previous release keeps serving.

**A failed deploy rolls its images back.** The tags currently serving are written to
`deploy/.rollback` *before* anything changes. After `up -d` the workflow polls `/login`
(200) and the protected `/ops` route (307), then checks service health, scheduled jobs,
staff-level API reads on the VPS. A failed check
restores the previous image tags. Migrations are not rolled back; keep schema
changes compatible with the prior image. Old tagged images are retained for rollback.

To roll back by hand, run the Deploy workflow with a previous SHA as the `tag` input. It
pulls the existing images under that tag without rebuilding current source. This works
when CI is red; check schema compatibility before using an older image.

## Storage baseline

The current PostgreSQL database, media volume, and export volume live on the VPS.
Backup production is paused while the storage baseline is established.

## History

The pre-Django pipeline (FastAPI, SQLite, a single-process CLI) was removed in favour of
this platform, and its source is in git history.

The migration path off it is gone too. `manage.py import_legacy` read a SQLite corpus that
no longer exists anywhere, so the command could not run; it was deleted rather than left as
an entry in `--help` that fails on its first argument. Recover it from git history if the
old database ever resurfaces. Nothing in the running system depends on it, and removing it
left `core` with no imports into any app above it.
