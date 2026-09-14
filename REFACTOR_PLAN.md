# Refactor plan

Phase 0 recon for a simplification pass over this repository. Read-only; no source file
was modified to produce it. Every claim below is backed by a command whose output is
reproducible from a clean checkout.

## Headline

**This codebase does not need dramatic simplification.** It has already had it — the git
log is a sequence of correctness and consolidation passes ("delete nine unreachable
definitions", "Remove the superseded pre-Django pipeline and document the real system").
Mechanical recon found essentially nothing to cut:

| Check | Method | Result |
|---|---|---|
| Dead backend symbols | Every top-level `def`/`class`/CONST in non-test, non-migration `.py`, grepped for inbound references across the whole tree | **0 real.** 13 hits, all false positives: Django `AppConfig` subclasses, Celery settings consumed by namespace, autouse pytest fixtures |
| Dead frontend exports | Same sweep over `frontend/lib` and `frontend/components` | **0** |
| Production-code duplication | `jscpd --min-lines 8 --min-tokens 60` | **0.** All 19 clones are captured HTML test fixtures (`sources/tests/fixtures/`) plus one 15-line block inside `api/tests/test_api.py` |
| Frontend import cycles | `madge --circular` over `app`, `lib`, `components` | **0** |
| Backend module cycles | Cross-app import matrix, then per-module verification of every deferred import | **0 at module level** (see Batch 8) |
| Committed secrets | `git ls-files` for `.env`/key/cert patterns, plus `git log --all -- '*.env'` | **None.** `.env`, `backend/.env` and `deploy/.env` are untracked and correctly ignored |
| Framework idiom | Layout vs. Django 5.2 app-per-domain and Next 15 App Router conventions | **Already conventional** |

What remains is a small, evidenced set: two dead artifacts, one settings entry pointing at
a directory that does not exist, one literal duplicated across four frontend files, one
module whose sole reason to exist is a self-aliasing re-export, and the Phase 4 ergonomics
that were never written. The goal is to remove the last four "why does this file exist?"
moments — not to hit a line-count target.

## Stack

Django 5.2.17 LTS + DRF 3.18 on Python 3.13; Postgres 16 with pgvector; Celery 5.6 over
Redis 6.4 with two worker pools and beat; Next.js 15.5 App Router on Node 24, server
components only, Tailwind 4, no client-side data fetching. Eight Django apps — `core`,
`sources`, `articles`, `inference`, `review`, `market`, `exports`, `api`. Tooling: ruff
0.16.6, pytest 9.1.1 + pytest-django, `node --test` for the frontend. `package-lock.json`
is committed and current; Python deps are pinned exactly in `requirements*.txt`.

## Current architecture

A request to a dashboard page enters Caddy on the VPS, which file-serves `/media/*` off a
shared volume, proxies `/admin/*` and `/static/*` to gunicorn, and sends everything else
to Next. `middleware.js` is a fail-closed login gate that checks only for the presence of
the `news_token` cookie. The page is a server component; it calls `lib/api.js`, which
attaches the httpOnly token server-side and fetches Django over the private network. DRF
serializes, and the page streams back through `AsyncPanel` boundaries so one slow or
failing endpoint degrades a panel rather than the page.

Writes never originate from the browser. Celery beat fires 14 periodic tasks from rows in
the `django_celery_beat` tables, installed by `manage.py setup_schedule`; the crawl and
inference pools consume separate queues so a slow crawl cannot block inference.

Layering is honest: `core` holds the vocabulary, the notify rule, the error taxonomy and
the SSRF-guarded fetcher, and everything imports down into it. The one wrinkle is that
`core/management/commands/` also holds the *orchestrators* (`run_pipeline`,
`import_legacy`), which import upward into every other app — so `core` is simultaneously
the bottom layer and a top layer. That is documented rather than fixed; see "Left alone".

## Target architecture

The same one. This is the conventional Django layout — one app per bounded context, models
and tasks inside the app that owns them, a single `api` app holding the read surface, a
`config` package for settings/wsgi/asgi/celery — and the conventional Next App Router
layout: route segments under `app/`, shared presentation in `components/`, server-side I/O
in `lib/`, one `middleware.js`. Both already match their framework's grain, so the target
is to *stop deviating* in the four small places listed below, not to impose a new shape.

## Deployment reality

Every batch has to survive this pipeline, because it ships on merge.

- **CI** (`.github/workflows/ci.yml`): `manage.py check` → `check --deploy --fail-level
  WARNING` against **prod** settings → `makemigrations --check --dry-run` → `pytest -q` →
  `ruff check .` → `pip-audit` → the `deploy/tests` unittest suite. Frontend: `npm ci` →
  `npm audit --omit=dev --audit-level=low` → `npm test` → `npm run build`. Both Dockerfiles
  are built (not pushed) so a broken base image surfaces before the deploy.
- **Deploy** (`deploy.yml`, on push to `main`): build and push both images to GHCR tagged
  by commit SHA and `latest` → `scp` the compose file and `backup.sh` to the VPS → rewrite
  `BACKEND_IMAGE`/`FRONTEND_IMAGE` in the host `.env` to pin this SHA → `docker compose
  pull && up -d --remove-orphans` → poll `https://$NEWS_DOMAIN/login` for a 200, 20 times
  at 6-second intervals. On failure it dumps `ps` and the last 80 log lines.
- **Migrations run automatically**, in a one-shot `migrate` service that also runs
  `collectstatic` and `setup_schedule`. The app services gate on it via
  `service_completed_successfully`, so schema changes land before anything serves them.
  A schema change therefore ships in the same deploy as its code.
- **No staging, no canary.** The only health gate is one 200 on `/login`. A regression
  confined to `/ops`, `/kpi`, the workbook exporter or a Celery worker deploys green.
  This materially raises the risk of every batch and is why they are small below.
- **Rollback:** Actions → Deploy → *Run workflow*, with `tag` set to the previous good
  SHA. That re-pins both images and re-runs `up -d`. Code-level rollback is
  `git revert <sha>` && push, which re-triggers the same path. Never force-push, never
  `reset --hard` on `main`.

### Reachable only by string — never treat as dead

Static analysis cannot see any of these:

- `core/management/commands/run_pipeline.py` resolves every stage through
  `__import__(module_path, fromlist=[task_name])` over its `STAGES` dict — 15 tasks across
  six apps, referenced only as string pairs.
- Every `@shared_task(name="…")` string (21 of them) is both a Celery routing key and a
  row in the VPS `django_celery_beat` PeriodicTask table, written by `setup_schedule`.
  Renaming one strands in-flight messages.
- Compose commands name `config.wsgi:application`, `config.celery.app`, and the management
  commands `migrate`, `collectstatic`, `setup_schedule`.
- `deploy/backup.sh` is bind-mounted into the `backup` service by host path.
- Django dotted paths: `INSTALLED_APPS`, `MIDDLEWARE`, `REST_FRAMEWORK` (auth, permission,
  filter, pagination and throttle classes), `STORAGES`, `LOGGING`, `CELERY_BEAT_SCHEDULER`.
- `sources/strategies/__init__.py` maps `Strategy` enum *values* to modules in `REGISTRY`,
  and derives `BACKFILLABLE` via `hasattr(module, "backfill")` — a strategy module is
  reached by enum value, never by a named import at the call site.
- `settings.PROMPTS_DIR / f"{name}.md"` loads the three prompt texts by constructed path.

## Verification for this pass

Local backend gates are unavailable: Docker is not running (no Postgres, no Redis) and
`backend/.venv` is Python 3.11 with Django 5.1.5, ruff 0.8.6 and pytest 8.3.4 — stale
against the pinned Python 3.13 / Django 5.2.17 / ruff 0.16.6 / pytest 9.1.1. By decision,
this pass runs **CI-only**. For each batch:

1. Run what does work locally: `npm test` (12 tests, currently green) and `npm run build`
   for any frontend batch, plus an exhaustive repo-wide grep for every removed identifier,
   filename and string — including CI files, compose, the Caddyfile, Dockerfiles,
   `.dockerignore`, Markdown, and Celery task-name literals.
2. Push one batch, then watch it land before starting the next: CI green → Deploy green →
   `/login` returns 200 → `/ops` and `/exports` render → container logs since the deploy
   show no new `ImportError`, 5xx, or dead letters.
3. On any failure, `git revert` and push immediately, confirm recovery, then diagnose.
   Never debug forward on a broken deploy.

Batches are kept far under the 400-line ceiling, because with no local gate a red CI is
only discovered once the commit is already on `main`.

## Batches, lowest risk first

**0 — this file.** Committed alone, no source touched.

**1 — delete `work/`** (14 files, ~475 lines). Point-in-time audit evidence from two
completed review sessions. Grep for `work/e2e-audit` and `work/independent-review` across
the tree returns hits only from inside `work/` itself. Not an entrypoint, not imported,
absent from CI and compose. Git history preserves them.

**2 — delete `backend/bakeoff_report.json`** (8 KB). The string `bakeoff` matches zero
files repo-wide. `benchmark_models` writes `settings.BASE_DIR / f"{run_id}.json"` and
never reads a report back, so this is one stale run's output. Regenerable.

**3 — ignore-file hygiene.** Add `.cursor/` (present, empty, untracked, unignored).
Extend `backend/.dockerignore`, which currently misses `.pytest_cache`, `.ruff_cache`,
`var/` and `*/tests/` — all shipped into the GHCR build context on every deploy. No
source change.

**4 — drop the phantom template directory.** `config/settings/base.py` sets
`TEMPLATES[0]["DIRS"] = [BASE_DIR / "templates"]`; that directory does not exist and no
app in this repo ships a template. `APP_DIRS: True` is what actually resolves the admin
and DRF browsable-API templates, and is unchanged. One line. CI's deploy check exercises
the result.

**5 — one home for `API_ORIGIN`.** The literal
`process.env.API_ORIGIN || "http://127.0.0.1:8000"` is written out four times:
`lib/api.js:20`, `app/logout/route.js:17`, `app/login/actions.js:6`, `next.config.mjs:22`.
Export it once from `lib/api.js`; import it in the three runtime call sites. `next.config.mjs`
keeps its own copy deliberately — it is evaluated by the Next CLI before the `@/` alias
exists, and reaching into `lib/` from there is the fragile option. ~15 lines; `npm test`
and `npm run build` gate it locally.

**6 — fold `articles/url_health.py` into `articles/tasks.py`.** The clearest "why does
this file exist?" in the repo. `url_health.py` defines a task named
`articles.tasks.check_stale_urls` — a name that is only truthful because
`articles/tasks.py:21` carries `from .url_health import check_stale_urls as
check_stale_urls`, a self-aliasing re-export whose entire job is to make that name resolve
for `run_pipeline`'s `__import__`. 83 lines move, `note_gone` with them (its other caller
is `sources/extraction.py:93`). **The `name=` string is preserved byte-for-byte**, so the
routing key, the PeriodicTask row and `run_pipeline`'s `("articles.tasks",
"check_stale_urls")` entry all keep working. Pure move, no logic edit; afterwards a grep
for `url_health` must return zero.

**7 — rename `inference/prompts/` to `inference/prompt_texts/`.** A module
(`inference/prompts.py`) and a data directory (`inference/prompts/`) share a name. Python
resolves the module and the three `.md` files load fine, but a reader and an IDE both see
two things called `prompts`. `settings.PROMPTS_DIR` is the directory's single referent.
Verified safe: `prompt_version()` is a sha256 of the prompt **text**
(`inference/prompts.py:142`), not of any path, so stored provenance and A/B comparability
are untouched.

**8 — hoist function-local imports that are not breaking a cycle.** Six deferred imports
paper over cycles that do not exist: `inference/memory.py:134` (`review.models`) and `:236`
(`market.models`), `articles/tasks.py:44,55,268` (`inference.budget`),
`articles/dedupe.py:128` (`inference.models`), `market/tasks.py:140`, and two in
`api/views.py`. Each target was checked: `review/models.py` and `market/models.py` import
nothing from `inference`, and `inference/budget.py` imports only `core`. Hoisting makes
the real dependency graph visible to tooling. **Optional, and run last** — import order at
Django startup is exactly the kind of thing that passes every test and fails on boot.

**9 — make both `.env.example` files true.** `backend/.env.example` pins
`GAPGPT_MODEL=gemini-2.5-flash-lite` while `config/settings/base.py` and
`deploy/.env.example` both say `gemini-3.1-flash-lite`, so a developer copying it
benchmarks a different model than production. It also omits ~15 variables the code reads:
`THROTTLE_LOGIN`, `THROTTLE_SIGNUP`, `DRF_NUM_PROXIES`, the three `NEWS_CIRCUIT_*`,
`NEWS_INFERENCE_PREFLIGHT`, `NEWS_HTTP_TIMEOUT`, `NEWS_USER_AGENT`, `EXPORT_DIR`,
`BACKUP_DIR`, `CACHE_URL`, `MEDIA_ROOT`, `POSTGRES_CONN_MAX_AGE`, `CELERY_TASK_TIME_LIMIT`,
`CELERY_RESULT_BACKEND`, `DJANGO_LOG_LEVEL`, `BACKUP_RETENTION_DAYS`. Example files only —
placeholders, no real values, no runtime effect. **Caveat stated in the commit:** the VPS
`.env` is hand-written, so a key added to `deploy/.env.example` does *not* reach the
server; the commit will list exactly which keys need a manual edit on the box.

**10 — `Makefile`, `ARCHITECTURE.md`, README trim.** One command each for dev, test, lint
and build; today the README's six-line venv incantation is the only entry point.
`ARCHITECTURE.md` gets the layer diagram, the directory map, and the rules a contributor
must not break — chief among them that `@shared_task(name=…)` strings are a wire contract,
and that `core.scoring.decide` is the only implementation of the notify rule. The README
is accurate and mostly stays; it loses only the instructions the Makefile now owns.

## Deletion candidates

| Path | Evidence | Confidence | If wrong |
|---|---|---|---|
| `work/**` (14 files) | Zero inbound references outside itself; absent from CI, compose, imports | High | Historical review notes lost; recoverable from git |
| `backend/bakeoff_report.json` | `bakeoff` matches zero files repo-wide; `benchmark_models` never reads a report | High | Nothing; regenerable |
| `TEMPLATES["DIRS"]` entry | Directory does not exist; zero template files in the repo | High | Admin/DRF templates — but those resolve through `APP_DIRS`, unchanged |
| `articles/url_health.py` (merged, not deleted) | Only importer is the self-aliasing re-export in `tasks.py` | High | `check_stale_urls` unroutable — prevented by preserving the `name=` string verbatim |

## Suspected dead — needs runtime confirmation, not deleting

- **Root `var/` (11 MB)** — the orphaned output tree from the pre-Django pipeline. It is
  the legacy workbook corpus, so it is data, not code. Untracked and already ignored, so
  this is a local-disk question rather than a commit. Not mine to destroy.
- **Root `.venv/` (190 MB)** — the dead FastAPI-era environment (`fastapi`, `httpx`, no
  Django). Harmless, but it is what a new engineer's shell picks up first, and it is why
  the backend gates could not run locally. Untracked; removing it is a local operation.
- **`django.contrib.admin`** — no app defines an `admin.py`, so `/admin/` exposes only
  Users, Tokens and beat schedules. That looks deliberate (the README directs you there to
  activate an A/B variant, and `AppShell` links staff to it), so it stays. Confirm by use
  before anyone proposes removing it.

## Bugs and fragile patterns — reported, not fixed

1. **Celery task names are inconsistent across apps.** All five `articles` tasks use a
   full module path (`articles.tasks.download_image`, `…download_pending_images`,
   `…backfill_dedupe`, `…reapply_prefilter`, `…check_stale_urls`); every other app uses
   app-level names (`inference.run_cycle`, `sources.crawl_all`,
   `exports.build_daily_workbook`, `review.sample_review_cases`, `market.poll_prices`).
   Unifying them is a **behaviour change**, not a rename: the string is the routing key,
   it is persisted in the VPS beat table, and any message queued under the old name
   dead-letters. Doing it safely means dual-registering both names, deploying, re-running
   `setup_schedule`, draining the queues, then removing the alias in a later deploy.
2. **`backend/.env.example` model drift** — fixed in Batch 9, but worth naming on its own:
   a local bake-off silently measures a different model than the one production runs.
3. **`EXPORT_DIR` and `BACKUP_DIR` appear in neither `.env.example`**, although compose
   sets both and `/ops` reports backup freshness from one of them.
4. **The deploy's only health gate is one 200 on `/login`.** Recommended follow-up: extend
   the post-deploy poll to hit `/api/health/` (which already checks the database and cache)
   and one authenticated dashboard, so a broken aggregate cannot deploy green.

## Deliberately left alone

`core/scoring.py`, `core/vocabulary.py`, `core/net.py`, `api/filters.py`,
`inference/circuit.py`, `inference/budget.py`, and every authentication path: correct,
self-contained, not duplicated, and several are marked frozen invariants tied to a
documented production incident. `api/views.py` is 815 lines, but each view is a distinct
endpoint with no duplication between them — splitting it would add files without making
anything easier to find. Migrations, the CI/CD workflow definitions, the Caddyfile, the
compose files and `backup.sh` are untouched. `core/management/` keeps its orchestrator
commands despite the layering wrinkle: moving a management command risks it silently not
being discovered, for no gain a reader would notice. The dense explanatory comments
throughout are this repo's best feature and are not churn targets.

## End-to-end verification

After the final batch, against the live deployment:

1. CI and Deploy both green on `main`.
2. `curl -s -o /dev/null -w '%{http_code}' https://$NEWS_DOMAIN/login` → `200`.
3. Signed in: `/`, `/article/[id]`, `/ops`, `/kpi`, `/market`, `/exports` all render, and
   one workbook downloads.
4. `docker compose -f docker-compose.prod.yml ps` → every service healthy, `migrate`
   exited 0.
5. `docker compose logs --since <deploy>` for `backend frontend worker-crawl
   worker-inference beat` → no `ImportError`, no 5xx, no new dead letters.
6. `manage.py run_pipeline url-health --now` → `check_stale_urls` still resolves after
   Batch 6 and returns its counts dict.
7. `/ops` shows beat still firing: recent runs advancing, backup age under 36h.

Then `REFACTOR_REPORT.md` — before/after counts, every commit and what it did, the
suspected-dead list with instrumentation plans, the bugs above, and ranked follow-ups.
