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
Use `make help` for all targets.

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
