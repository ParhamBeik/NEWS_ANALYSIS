# Architecture

## Layers

Dependencies flow downward:

```text
transport       API views/serializers/filters, frontend routes, CLI commands, Celery tasks
      ↓
domain          scoring, vocabulary, Persian text, errors, prefilter, dedup, prompt loading
      ↓
data access    Django models, memory retrieval, price access, source extraction/strategies
      ↓
infrastructure  HTTP guards, provider clients, budget/circuit controls, settings, Celery
```

Transport code should parse, authorize, delegate, and serialize. Domain code should hold shared
rules and stay free of SQL where practical. Infrastructure owns external systems and limits.

## Directory map

```text
backend/config       settings, URLs, ASGI/WSGI, Celery
backend/core         shared rules and operator commands
backend/sources      crawling and extraction
backend/articles     article data and ingest
backend/inference    LLM policy, providers, guards, tasks
backend/review       human labels and A/B judging
backend/market       prices and backtests
backend/exports      workbook generation
backend/api          read API
frontend              server-rendered dashboard
deploy                Compose, Caddy, backups, release checks
```

## Invariants

1. Celery task names are persisted routing contracts. Rename only with a compatibility period.
2. Celery tasks live in their app's `tasks.py` so autodiscovery registers them.
3. `core.scoring.decide` is the only notify-rule implementation.
4. Applied migrations are append-only; use expand, migrate, then contract.
5. Prompt files are runtime inputs. Their content hash is the prompt version stored with results.
6. Secrets come from the environment and must never be logged or committed.

## Operational files

The shell scripts in `deploy/` are live deployment inputs, not examples:

- `backup.sh` produces and validates database dumps.
- `copy-backup.sh` sends a verified dump to an SSH destination.
- `pull-backup.sh` verifies a VPS dump on the Mac.
- `check-stack.sh` checks service health, API reads, schedules, and off-host backup freshness.

Run `make ci` and the backup unittest suite after changes. Do not delete a task, prompt, compose
mount, migration, or management command because static analysis cannot find its caller; several
are referenced by Django or Celery strings.
