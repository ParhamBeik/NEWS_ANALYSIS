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
| Source catalog | `backend/sources/` (`fixtures/sources.yaml`, `strategies/`) | 44 catalog sources (Phase 1, 2026-10-02) with language, ownership group, license mode and role; loaded on every deploy by the `migrate` service |
| Collection | `sources/tasks.py`, `articles/ingest.py` | Live (fixed 2026-10-01 after a 4.5 h outage) |
| Article versions | `articles.ArticleRevision` | Live: prior text kept on edit/removal |
| Events | `core/events.py`, `articles.NewsEvent` | Live: created per new article |
| AI decisions (Jev) | `inference/jev.py`, `inference/tasks.py` `assess_event` | Built; **stalled: GapGPT wallet empty**; TypeSafe key not yet set |
| Topics + watch items | `core/vocabulary.py`, `core/watch.py`, `articles/fixtures/watch_items.yaml` | Built (Phase 2): 8 investor topics; ~165 bilingual assets/actors/themes tagged per event |
| Reader tiers | `core/tiers.py` | Built (Phase 2): 1-5 relative to the last 30 days; fixed bands under 200 scored events |
| Grouping memory | `articles.GroupingDecision`, `core/events.py` | Built (Phase 2): staff splits are never re-merged |
| Storylines | `core/storylines.py`, `inference.build_storylines` (02:30 nightly) | Built (Phase 2); names wait on AI |
| Evidence level | `NewsEvent.evidence_level` | Placeholder: single/multi/official from source groups |
| Briefs | `inference/jev.py` `brief`, `summarize_event` | Built; waits on AI decisions; stop at 80% of the monthly budget |
| AI budget guard | `inference/budget.py`, `inference/circuit.py` | Live; caps run/day/month |
| Reader radar | `frontend/app/page.js` | Live (image-led, categories, tiers) |
| Event page | `frontend/app/events/[id]/` | Live |
| Market-impact chart | `frontend/app/events/[id]/market/` | Live; asset data limited until portfolio contract |
| Staff swipe review | `frontend/app/review/swipe/`, `core/review.py` | Live (staff login) |
| Old article pipeline | `inference` classify/evaluate/summarize, `/review`, `/kpi`, workbooks | Schedule **disabled** (replaced by events); workbooks stale until re-fed |
| Alerts (web push) | `articles.AlertSubscription`, `NEWS_ALERTS_ENABLED` | Built; off |
| Ops dashboard | `frontend/app/ops/`, `api` `OpsView` | Live |
| Deploy | `.github/workflows/`, `deploy/` | `main` → CI → GHCR → Mac runner → server; health gate + auto-rollback |

## Blocked: network

Checked from the Tehran server (45.139.10.12) on 2026-10-02 with
`curl -sL -m 20 -A 'Mozilla/5.0 ...'`. None of these are in the catalog enabled.

| Source | URLs tried | Exact failure |
|---|---|---|
| Fars | `https://www.farsnews.ir/rss`, `/rss/latest`, `/rss.xml`, `/showrss` | HTTP 200 `text/html`, 4,008 bytes: a JavaScript app shell (redirects to `farsnews.ir`), no XML, no `rss` link on the homepage |
| Fars | `https://farsnews.ir/api/rss` | curl exit 28, timed out after 20 s |
| OFAC recent actions | `https://ofac.treasury.gov/recent-actions/rss`, `/recent-actions/feed`, `/recent-actions.xml` | HTTP 404 |
| OFAC recent actions | `https://ofac.treasury.gov/rss.xml` | HTTP 200, but it lists sanctions programs, not actions; newest item 2025-02-12 |
| OFAC recent actions | `https://home.treasury.gov/system/files/126/ofac.xml` | HTTP 403 (redirected to `ofac.treasury.gov`) |
| World Bank | `https://www.worldbank.org/en/rss/news`, `/en/news/rss.xml`, `/en/news/all.rss` | HTTP 404 |
| World Bank | `https://www.worldbank.org/en/news/all?displayconttype_exact=Press+Release&format=rss` | HTTP 200 `text/html`, 4,920 bytes, no items |
| World Bank | `https://search.worldbank.org/api/v2/news?format=atom` | HTTP 200 Atom, but XML parse fails: `unbound prefix: line 8, column 4` (undeclared `wb:` fields, no per-entry title or link) |
| Tasnim | every endpoint (2026-09, Frankfurt) | connection refused, curl exit 000; not rechecked |

Notes: `feeds.a.dj.com/rss/RSSWorldNews.xml` (WSJ) still answers but its newest item is
2025-01-27, so the catalog uses `feeds.content.dowjones.io/public/rss/RSSWorldNews`.
Sena's feed was current but its newest item was 2026-09-30 (market closed Thu-Fri).
IAEA dates most items as `26-10-02  10:45`, which does not parse; those rows are stored
with `date_uncertain`.

## Owner inputs pending

1. Top up GapGPT (AI is stalled until then).
2. TypeSafe API key → `TYPESAFE_API_KEY` in the server `.env` (Jev; cheaper than fallback).
3. `NEWS_MONTHLY_BUDGET_USD=30`, `NEWS_DAILY_BUDGET_USD=1.00` in the server `.env`.
4. Later phases: Kavenegar (SMS login), Firebase + Pushe/Najva (mobile push).

## Next build phases

1. Collection backbone: source catalog to ~38, coverage gaps, durable retries.
2. AI backbone: 8 investor topics, watch-item vocabulary, quantile tiers, storylines (built).
3. Ops page for coverage and AI cost; 4. portfolio price contract; 5. accounts, watchlists,
   alerts; 6. mobile app.
