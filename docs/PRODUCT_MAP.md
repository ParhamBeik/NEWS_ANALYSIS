# Product map

One page for the owner: what the product is, where each part lives, and what state it is
in. The full decision record is the planning ledger
(`~/.claude/plans/all-right-so-basically-cuddly-hearth.md`); this file is the map.

**Product:** a bilingual (Persian first, Jalali dates) news radar for Iranian investors.
It collects Iranian and international news, groups reports of the same occurrence into
events, scores how much each event may matter to Iranian investors and globally, writes
short attributed briefs for the important ones, and shows them on an image-led radar.
Live at `https://news.parhambm.ir`, hosted on the shared Tehran server (45.139.10.12).

## How a story flows

```
sources ─▶ crawl (every 2 min) ─▶ article stored + versioned ─▶ event (same occurrence)
   ─▶ Jev decision: topic, Iran score, global score, asset relevance, same-event?
   ─▶ brief (only if score ≥ 75) ─▶ reader radar / event page / market-impact chart
   ─▶ staff swipe review (labels calibrate the model)        ─▶ alerts (off until gated)
```

## Parts, where they live, status (2026-10-01)

| Part | Code | Status |
|---|---|---|
| Source catalog | `backend/sources/` (`fixtures/sources.yaml`, `strategies/`) | Live, all 14 catalog sources loaded in prod (2026-10-01) |
| Collection | `sources/tasks.py`, `articles/ingest.py` | Live (fixed 2026-10-01 after a 4.5 h outage) |
| Article versions | `articles.ArticleRevision` | Live: prior text kept on edit/removal |
| Events | `core/events.py`, `articles.NewsEvent` | Live: created per new article |
| AI decisions (Jev) | `inference/jev.py`, `inference/tasks.py` `assess_event` | Built; **stalled: GapGPT wallet empty**; TypeSafe key not yet set |
| Briefs | `inference/jev.py` `brief`, `summarize_event` | Built; waits on AI decisions |
| AI budget guard | `inference/budget.py`, `inference/circuit.py` | Live; caps run/day/month |
| Reader radar | `frontend/app/page.js` | Live (image-led, categories, tiers) |
| Event page | `frontend/app/events/[id]/` | Live |
| Market-impact chart | `frontend/app/events/[id]/market/` | Live; asset data limited until portfolio contract |
| Staff swipe review | `frontend/app/review/swipe/`, `core/review.py` | Live (staff login) |
| Old article pipeline | `inference` classify/evaluate/summarize, `/review`, `/kpi`, workbooks | Schedule **disabled** (replaced by events); workbooks stale until re-fed |
| Alerts (web push) | `articles.AlertSubscription`, `NEWS_ALERTS_ENABLED` | Built; off |
| Ops dashboard | `frontend/app/ops/`, `api` `OpsView` | Live |
| Deploy | `.github/workflows/`, `deploy/` | `main` → CI → GHCR → Mac runner → server; health gate + auto-rollback |

## Owner inputs pending

1. Top up GapGPT (AI is stalled until then).
2. TypeSafe API key → `TYPESAFE_API_KEY` in the server `.env` (Jev; cheaper than fallback).
3. `NEWS_MONTHLY_BUDGET_USD=30`, `NEWS_DAILY_BUDGET_USD=1.00` in the server `.env`.
4. Later phases: Kavenegar (SMS login), Firebase + Pushe/Najva (mobile push).

## Next build phases

1. Collection backbone: source catalog to ~38, coverage gaps, durable retries.
2. AI backbone: 8 investor topics, watch-item vocabulary, quantile tiers, storylines.
3. Ops page for coverage and AI cost; 4. portfolio price contract; 5. accounts, watchlists,
   alerts; 6. mobile app.
