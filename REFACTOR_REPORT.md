# Refactor report

Ten batches, ten commits, all on `main`, each one deployed to production and verified green
before the next was started. Baseline `a36a0a8`, head `8696ebf`.

Two follow-ups landed after the pass, at your request: `4e9bb02` fixes the sign-out redirect
recorded below as bug 1, and the local-only cleanup described under "Suspected dead" is done.

## The honest headline

**This codebase did not need dramatic simplification, and did not get it.** Phase 0 recon
found no dead code, no production-code duplication, no import cycles, no unused
dependencies and a layout already idiomatic for Django 5.2 and Next 15. The work that
remained was four genuine "why does this exist?" removals and the ergonomics that had never
been written. Chasing a larger number would have meant churn, and churn on a repo that
auto-deploys to production with a single health check is expensive.

## Numbers

| | Before | After |
|---|---|---|
| Tracked files | 212 | 198 |
| Source lines (`.py`/`.js`/`.mjs`) | 18,074 | 18,090 |
| Runtime dependencies (Python / Node) | 19 / 3+2 | 19 / 3+2 |
| Module-level import cycles | 0 | 0 |
| Docker build context (backend) | +46 MB of tool caches | excluded |

Source lines went **up by 16**. Batch 6 replaced a re-export with the code it pointed at
and added the comment explaining why every task must live in `tasks.py`; Batch 7 added the
note about the namespace-package shadowing hazard. That is the correct trade and it is why
line count was never the target — the brief's measure is whether a new engineer can find
things, not how much was deleted.

Net diff: 39 files, +733 / −852.

## Commits

| SHA | What it did |
|---|---|
| `4616668` | Recorded Phase 0 recon and the batch plan (`REFACTOR_PLAN.md`), no source touched |
| `288b530` | Deleted `work/` — 15 point-in-time review reports, zero external references |
| `d2bd5ed` | Deleted `backend/bakeoff_report.json` — string `bakeoff` matched zero files repo-wide |
| `8d50fb2` | Kept tool caches out of the Docker build context; `.cursor/` into `.gitignore` |
| `8ac3445` | Dropped `TEMPLATES["DIRS"]`, which pointed at a directory that never existed |
| `bcd2b2e` | Declared the Django origin once instead of four times (frontend) |
| `db18961` | Folded `articles/url_health.py` into `articles/tasks.py`, where autodiscover looks |
| `4db617f` | Renamed `inference/prompts/` → `prompt_texts/` so it cannot shadow `prompts.py` |
| `a756d91` | Made both `.env.example` files complete and true |
| `8696ebf` | Added `Makefile` and `ARCHITECTURE.md`; pointed the README at them |

## Architecture, before and after

The layer structure did not change, because it was already right. Two things moved:

```
  before                                   after
  backend/articles/                        backend/articles/
    tasks.py  ← re-exports url_health        tasks.py  ← every articles task
    url_health.py  ← holds a task that
                     tasks.py must alias
                     for its own name to
                     be true

  backend/inference/                       backend/inference/
    prompts.py    (module)                   prompts.py       (module)
    prompts/      (directory, shadows        prompt_texts/    (directory, cannot shadow)
                   the module if anyone
                   ever adds __init__.py)
```

`ARCHITECTURE.md` now carries the layer diagram, the directory map, the four rules that are
expensive to learn by breaking, and the list of things reachable only by string.

## Verification

Backend gates could not run locally at the start (both virtualenvs stale, Docker down), so
the plan was approved as CI-only. Partway through I built a Python 3.13 venv from the pinned
requirements with `uv`, which gave back ruff 0.16.6 and `manage.py check` — everything
except pytest, which needs Postgres. That paid for itself immediately on Batches 6 and 7.

Per batch: repo-wide grep for every removed identifier, filename and string; `npm test` and
`npm run build` for frontend batches; ruff + `manage.py check` for backend batches; then
push, watch CI **and** Deploy to green, and confirm the site serves before starting the
next. No batch was started on a red pipeline and none needed reverting.

Two batches got verification beyond the standard set, because both could have failed
silently rather than loudly:

- **Batch 6** — dumped the Celery registry: all 20 tasks register, all 15 `run_pipeline`
  stages resolve, all 14 scheduled names resolve. The risk was an unregistered task name,
  which produces silence at 04:30 on a Sunday, not an error.
- **Batch 7** — `load_policy()` falls back to a built-in default rather than raising, so a
  wrong `PROMPTS_DIR` would have quietly changed the prompts sent to the model. Verified by
  hash instead of inspection: `prompt_version` is `p958115dbebd3` before and after, with all
  three policies still loading from disk.

Final end-to-end against the live deployment:

- CI and Deploy green on `main`; `/login`, `/signup`, `/admin/login/` all 200.
- All seven protected routes 307 to `/login` with the correct `next` parameter, and `/`
  correctly without one.
- `/static/admin/css/base.css` and `/icon.svg` serve; the Django admin login page renders
  with its own template, confirming Batch 4 did not break template resolution.
- `/media/exports/anything.xlsx` returns 404 — the Caddy rule keeping workbooks off the
  unauthenticated media volume still holds.
- Final repo-wide sweep for `url_health`, `bakeoff_report`, `e2e-audit`,
  `independent-review`, `inference/prompts/` and `GONE_STATUSES`: **zero hits.**

## Batch 8 was planned and deliberately not done

The plan included hoisting function-local imports that appeared to paper over cycles. On
inspection that premise was false, and I have the data rather than an opinion. A module
graph built from the AST, comparing module-level imports against module-level-plus-deferred:

- Today: **0 cycles.**
- If every deferred import were hoisted: **1 cycle** — `sources.extraction ↔
  articles.tasks`, which is the edge Batch 6 created and deliberately left deferred with the
  reason written in place.

Deferred imports turn out to be a consistent house style across 40+ sites here, used for
stdlib imports too. Hoisting a cherry-picked six would have made the codebase *less*
consistent, spent real risk on import-order failures at Django and Celery startup, and
delivered nothing a reader would notice. Left alone and documented in `ARCHITECTURE.md`.

## Suspected dead

Nothing was deleted on suspicion during the pass itself. Afterwards, on your instruction:

- **Root `.venv/` (190 MB) — deleted.** The dead FastAPI-era environment (`fastapi`,
  `httpx`, no Django). It was what a bare shell picked up first, and why the backend gates
  did not work at the start. Untracked, so a disk operation rather than a commit.
  `make setup` builds the correct `backend/.venv` on Python 3.13.
- **Root `var/` (11 MB) — archived, then deleted.** Not build output: it held `news.db`,
  the 9.9 MB pre-Django SQLite corpus that `manage.py import_legacy` reads, alongside three
  generated workbooks and four category feeds. Archived first to
  `~/Downloads/news-analysis-legacy-var-20260915.tar.gz` (2.5 MB, 17 entries, verified to
  contain `news.db`) because no other copy existed — the repository history never tracked
  it, and the offsite tarball it was believed to be in is not there.
- **`backend/.venv13/` — deleted.** Scratch toolchain built during the pass.

Still open:

- **`django.contrib.admin`** — no app defines an `admin.py`, so `/admin/` exposes only
  Users, Tokens and beat schedules. That looks deliberate (the README sends you there to
  activate an A/B variant). *Confirm by:* using it once before anyone proposes removing it.

## Bugs found

1. **Sign-out redirected to an unreachable host — FIXED in `4e9bb02`, after this pass.**
   `frontend/app/logout/route.js` built its target with
   `NextResponse.redirect(new URL("/login", request.url), { status: 303 })`. Behind the
   proxy `request.url` carries the address Next bound to inside the container, so production
   replied `Location: https://0.0.0.0:3000/login` and every sign-out navigated nowhere. The
   edge passes Location through untouched and the deploy health check only polls `/login`,
   so nothing caught it. Pre-existing, confirmed by diffing the line against `HEAD~1`.

   Fixed by returning a relative `Location`, which RFC 7231 permits and the browser resolves
   against the URL it actually requested — correct behind any proxy, with no forwarded-host
   parsing to keep in sync with the edge. Verified live: `303`, `Location: /login`,
   `Set-Cookie` expiring the token, and following the redirect lands on
   `https://<domain>/login` with `200`. Covered by a regression test.

The rest below remain open.

2. **Celery task names are inconsistent across apps.** All five `articles` tasks use a full
   module path; every other app uses app-level names. Unifying them is a behaviour change,
   not a rename — the string is a routing key, it is persisted in the VPS beat table, and a
   message queued under an old name dead-letters. Safe path: dual-register, deploy, re-run
   `setup_schedule`, drain, remove the alias in a later deploy.
3. **`{404, 410}` is spelled three ways.** Two were collapsed in Batch 6; the third is an
   inline literal at `sources/extraction.py:90`. Collapsing it needs the constant to live
   somewhere both modules can import without the `sources.extraction ↔ articles.tasks`
   cycle — most likely `core`. Left alone rather than forced.
4. **`MEDIA_ROOT` works by coincidence.** Compose mounts the media volume at `/app/media`
   and the settings default happens to be `BASE_DIR/media`, which is the same path. Nothing
   asserts that. Changing either alone silently splits stored images.
5. **`load_policy()` fails open.** A missing or misnamed prompt file returns a built-in
   default instead of raising, so a path mistake shows up only as a changed
   `prompt_version`. Given prompts are a frozen invariant, failing loudly would be better.

## Recommended follow-ups, ranked

1. **Widen the deploy health gate.** The only check is one 200 on `/login`, so a regression
   in `/ops`, `/kpi`, the workbook exporter or any Celery worker deploys green. Note that
   `/api/health/` is *not* publicly routed — Caddy sends everything but `/media`, `/admin`
   and `/static` to Next, and `next.config.mjs` deliberately declines to proxy `/api/*`. The
   gate should therefore poll an authenticated dashboard route, or run the check inside the
   container. *(This corrects the recommendation in `REFACTOR_PLAN.md`, which suggested
   `/api/health/` before I had confirmed the routing.)*
2. **Get the backend test gate working locally.** `make setup` now does it; running
   `make ci` before a push is the difference between catching a problem before or after it
   deploys.
3. **Copy the `backups` volume off the box.** The README already says this. Dumps sitting on
   the same host as the database cover a bad migration but not a dead disk, and that volume
   holds the human review labels — the one thing the pipeline cannot regenerate.
4. **Decide about `ruff format`.** `make fmt` exists but CI does not enforce formatting and
   the codebase has never been through it. It is a ~9,000-line diff and needs its own commit
   plus a CI step — which touches the pipeline definition, so it needs your approval.
5. **Unify the Celery task names** (bug 2), as a deliberate multi-deploy project.

## What was deliberately left alone

`core/scoring.py`, `core/vocabulary.py`, `core/net.py`, `api/filters.py`,
`inference/circuit.py`, `inference/budget.py` and every authentication path: correct,
self-contained, not duplicated, and several are frozen invariants tied to a documented
production incident. `api/views.py` is 815 lines, but each view is a distinct endpoint with
no duplication between them — splitting it would add files without making anything easier to
find. The six near-identical `Card`/`SectionTitle`/`table` blocks in `app/ops/page.js` would
clear the three-call-site bar for a `DataTable` primitive, but the markup differs per table
and collapsing it risks drift for a cosmetic gain.

Untouched per the brief's hard constraints: every migration, the CI/CD workflow definitions,
the Caddyfile, both compose files, `backup.sh`, and all lockfiles. `core/management/` keeps
its orchestrator commands despite importing upward into every app — moving a management
command risks it silently not being discovered, for a gain no reader would notice.

The dense explanatory comments throughout are this repo's best feature. They were extended
where I changed something, and otherwise left exactly as they were.
