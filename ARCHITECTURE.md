# Architecture

Where things live, and the four rules that keep it that way. The *why* behind individual
decisions is in the README's design notes and in the module docstrings; this file is the
map.

## Layers

Dependencies flow one way. Nothing lower imports anything higher.

```
  transport            api/views.py, api/urls.py, api/serializers.py, api/filters.py
                       frontend/app/**        (route segments, server components)
                       */management/commands  (the operator's CLI)
                       */tasks.py             (what Celery beat calls)
        │              thin: parse, authorise, delegate, serialise. no business rules.
        ▼
  domain               core/scoring.py     the notify rule
                       core/vocabulary.py  the analyst team's words
                       core/text.py        Persian folding, trigrams, Jalali dates
                       core/errors.py      Transient / Permanent / Fatal
                       sources/prefilter.py, articles/dedupe.py, inference/prompts.py
        │              pure where possible. no SQL, minimal framework.
        ▼
  data access          */models.py, inference/memory.py, market/tgju.py
                       sources/extraction.py, sources/strategies/*
        │
        ▼
  infrastructure       core/net.py (SSRF-guarded fetching), inference/providers.py
                       inference/budget.py, inference/circuit.py (Redis)
                       config/ (settings, celery, wsgi, asgi)
```

Verified: the repository currently has **zero** module-level import cycles.

## Directory map

```
backend/
  config/       settings/{base,dev,prod,test}, celery, urls, wsgi, asgi
  core/         vocabulary, notify scoring, Persian text, error taxonomy, HTTP guards,
                and the operator commands (run_pipeline, setup_schedule, import_legacy)
  sources/      source registry, crawl strategies, extraction, prefilter
  articles/     Article/Image/Embedding storage, ingest, dedup, URL health
  inference/    prompt variants, providers, budget + circuit guards, the three LLM nodes
  review/       human labelling queue, blinded A/B pairing
  market/       TGJU price snapshots, prediction back-test
  exports/      the Persian analyst workbook and the category text feeds
  api/          the read API and the three purpose-built dashboard documents

frontend/
  app/          route segments; every page is a server component
  components/   presentation primitives shared by every page
  lib/          api.js (the server-side Django client) and display.js (value → colour)
  middleware.js fail-closed login gate

deploy/         compose for dev and prod, the Caddy site block, backup.sh
```

## The rules

**1. A Celery task name is a wire contract, not a label.**
`@shared_task(name="…")` strings are routing keys, they are stored as rows in the VPS
`django_celery_beat` tables, and `core/management/commands/run_pipeline.py` resolves them
by string through `__import__`. Renaming one strands every message already queued under the
old name and silently stops a scheduled job. Changing a name means dual-registering both,
deploying, re-running `setup_schedule`, draining, and only then removing the alias.

**2. Every Celery task lives in its app's `tasks.py`.**
`autodiscover_tasks` imports `tasks.py` and nothing else. A task defined in a sibling
module is registered only if `tasks.py` happens to import it — and an unregistered task is a
name beat schedules and no worker answers. That is silence, not an error.

**3. The notify rule has exactly one implementation: `core.scoring.decide`.**
`api/filters.py` filters by asking `decide` for primary keys rather than re-expressing the
rule as ORM `Case`/`When` annotations, and pays a subquery for the privilege. A second copy
would drift the first time a threshold moved, and that drift is the bug this system was
rebuilt to remove — a sentinel substituted for "not assessed" suppressed 0 of 488 security
alerts. An unassessed axis is `None` and is excluded from the vote; "too few axes to decide"
is its own status.

**4. Migrations are append-only, and nothing in this repo drops data.**
Never edit, reorder or squash a migration that has run in production. A schema change ships
expand → migrate → contract across separate deploys: add nullable, write both, backfill,
read new, drop later. The `migrate` service runs automatically on every deploy, before
anything serves, so a migration lands in the same release as its code.

## Things that look dead and are not

Static analysis cannot see any of these. Check here before deleting anything.

- `run_pipeline.py`'s `STAGES` dict — 15 tasks referenced only as string pairs.
- The 20 `@shared_task(name=…)` strings, plus `config/celery.py`'s `task_routes`.
- Compose commands naming `config.wsgi:application` and `config.celery.app`.
- `deploy/backup.sh`, bind-mounted into the `backup` service by host path.
- Django dotted paths in `INSTALLED_APPS`, `MIDDLEWARE`, `REST_FRAMEWORK`, `STORAGES`,
  `LOGGING`, `CELERY_BEAT_SCHEDULER`.
- `sources/strategies/__init__.py`'s `REGISTRY`, keyed by `Strategy` enum *value*, with
  `BACKFILLABLE` derived via `hasattr(module, "backfill")`.
- `settings.PROMPTS_DIR / f"{name}.md"` — and note that `load_policy` falls back to a
  built-in default rather than raising, so a wrong path changes `prompt_version` silently.

## Conventions

- Python is linted by ruff (config in `backend/pyproject.toml`), line length 100.
  `make fmt` runs `ruff format`, but **CI does not enforce formatting** and the codebase
  has never been run through it. Doing so is a 9,000-line diff; it needs to be its own
  commit plus a CI step, not a drive-by.
- Deferred (function-local) imports are a deliberate house style here, used for stdlib and
  cross-app imports alike. Exactly one is load-bearing: `sources/extraction.py` importing
  `articles.tasks.note_gone`, because `articles/tasks.py` imports `build_session` from
  `sources/extraction.py` at module scope. That one is commented in place.
- The frontend is server components only. No client-side data fetching, no API route
  proxying `/api/*` to the browser — the token is httpOnly and stays on the server.
- Persian values are never translated for display. They are shown as stored, with an
  English gloss beside them.

## Commands

See `make help`. `make ci` runs the same gates as `.github/workflows/ci.yml`, in order.
