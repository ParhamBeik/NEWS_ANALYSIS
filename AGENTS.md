# Project instructions

## Purpose

News Intelligence is a Django, Celery, PostgreSQL/pgvector, Redis, and Next.js application
that crawls Iranian news, deduplicates it, runs inference, supports human review, and exports
Persian analyst workbooks.

## Layout

- `backend/`: Django apps, tasks, management commands, migrations, and tests.
- `frontend/`: Next.js server-rendered dashboard.
- `deploy/`: Compose files, Caddy configuration, backup scripts, and deployment checks.
- `.github/workflows/`: CI and deployment automation.
- `backend/inference/prompt_texts/`: runtime prompt policy files. These are code inputs, not prose documentation.

## Working rules

1. Run commands from the repository root unless a command says otherwise.
2. Keep business rules in `backend/core/`; transport layers should parse, authorize, delegate, and serialize.
3. Keep Celery tasks in each app's `tasks.py`; task names are persisted routing contracts.
4. Never edit or reorder an applied migration.
5. Never print credentials or commit `.env` files.
6. Prefer the smallest root-cause change. Add one focused check for non-trivial logic.

## Checks

```bash
make ci
backend/.venv/bin/python -m unittest discover -s deploy/tests -v
```

Do not push or deploy from a local change unless the user explicitly authorizes it.
