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
   ─▶ brief (impact tier ≥ 4, or ≥ 3 if watched; else a translated headline)
   ─▶ reader radar / event page / market-impact chart
   ─▶ staff swipe review (labels calibrate the model)        ─▶ alerts (off until gated)
```

## Parts, where they live, status (2026-10-03)

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
| Evidence level | `NewsEvent.evidence_level`, `core/events.py` | Built (Phase 2b): single/multi/official from independence groups; disputed when another group contradicts |
| Per-report stance | `articles.ArticleStance`, `inference/jev.py` `stance` | Built (Phase 2b): reports/supports/contradicts/updates asked with the same-event question; badges on the event page |
| Translated headlines | `inference.translate_event_title`, `articles.TitleTranslation` | Built (Phase 2b): one cheap GapGPT call for unbriefed events, cached per article; waits on AI |
| Takedown | `core/takedown.py`, `api/takedown.py`, `articles.TakedownLog` | Built (Phase 2b): staff hide/unhide events and reports with a reason; append-only audit log |
| Gap backfill | `sources.backfill_gap` | Built (Phase 2b): queued when a gap closes on an archive-capable source; 3 days / 200 articles max |
| Briefs | `inference/jev.py` `brief`, `summarize_event`, `core/tiers.py` `brief_eligible` | Built; impact tier ≥ 4, or ≥ 3 when on a watchlist; waits on AI decisions; stop at 80% of the monthly budget |
| AI budget guard | `inference/budget.py`, `inference/circuit.py` | Live; caps run/day/month |
| Reader radar | `frontend/app/page.js` | Live (image-led, categories, tiers) |
| Event page | `frontend/app/events/[id]/` | Live |
| Market-impact chart | `frontend/app/events/[id]/market/` | Live; asset data limited until portfolio contract |
| Staff swipe review | `frontend/app/review/swipe/`, `core/review.py` | Live (staff login) |
| Old article pipeline | `inference` classify/evaluate/summarize, `/review`, `/kpi` | Schedule **disabled** (replaced by events) |
| Analyst workbooks | `exports/workbook.py`, `exports.build_daily_workbook` (23:50 nightly) | Re-fed from events: occurrence = evidence level, gold = Jev gold relevance, security = Iran score (security topics only), notes = brief + watch items. «جهت طلا» stays **blank**: Jev predicts no direction. Last `EXPORT_KEEP_DAYS` (60) days kept |
| Event back-test | `market/reactions.py`, `market.EventReaction`, task `market.compute_event_reactions` (hourly) | Built: tier ≥3 events × relevant Portfolio assets; ±2h/+1d (global), +1/+3 trading days (Iran); \|z\| vs trailing 30 days. Skips (counted on /ops) until Portfolio is connected |
| Price source switch | `NEWS_MARKET_SOURCE=tgju\|portfolio` | `tgju` (default): pages read the TGJU poller; `portfolio`: they read Portfolio. Poller still runs |
| Alerts (web push) | `articles.AlertSubscription`, `NEWS_ALERTS_ENABLED` | Built; off |
| Reader accounts | `accounts/`, `core/otp.py`, `api/accounts.py`, `/login`, `/onboarding`, `/settings` | Built (Phase 5): phone OTP via Kavenegar, **off until keys**; staff password login unchanged |
| Watchlists + personal radar | `accounts.Watch`, `lib/reader.js` `boostWatched` | Built (Phase 5): ≥3 watch items at onboarding; watched events marked and lifted 5 places |
| Watchlist alerts | `core/alerts.py`, `accounts.fan_out_event`, `/inbox` | Built (Phase 5), behind `NEWS_ALERTS_ENABLED`: dial, 5 pushes/day, quiet hours 23-07, tier 5 exempt; inbox always; web push + FCM adapters, Pushe/Najva tokens stored only |
| Ops dashboard | `frontend/app/ops/`, `api` `OpsView`, `OpsStaffView`, `CalibrationView`, `core/ops.py` | Live; staff panels: AI cost vs ceilings, errors by cause, freshness SLO (Phase 3), market calibration per tier/asset class |
| Staff ops alerts | `core/ops_alerts.py`, task `core.ops_alerts` | Every 5 min, 6 h dedup; logs always, email/webhook once `EMAIL_HOST` / `OPS_ALERT_WEBHOOK_URL` are set |
| Deploy | `.github/workflows/`, `deploy/` | `main` → CI → GHCR → VPS runner (app-release); health gate + auto-rollback |

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

Everything below is built and waits only on a key, an account, a server edit or a call.
Server `.env` edits are by hand (prod `.env` is not generated from `.env.example`).

**Keys and money (AI is idle until 1 or 2)**
1. Top up GapGPT. Decisions (fallback), briefs, stance, translated titles, storyline names.
2. `TYPESAFE_API_KEY` → Jev decisions directly (cheaper; briefs still use GapGPT).
3. `NEWS_MONTHLY_BUDGET_USD=30`, `NEWS_DAILY_BUDGET_USD=1.00`; drop the now-ignored
   `NEWS_BRIEF_MIN_SCORE`.
4. Phone login: `KAVENEGAR_API_KEY`, `KAVENEGAR_OTP_TEMPLATE` (Verify template, one `%token`).
5. Push: `NEWS_VAPID_*` (web); Firebase project + `google-services.json` and
   `FCM_PROJECT_ID`/`FCM_CREDENTIALS_FILE` (app; needs a read-only compose mount); choose
   Pushe or Najva (adapter + native SDK are written after the choice).
6. Optional: SMTP `EMAIL_*` (digest + staff ops notices), `OPS_ALERT_WEBHOOK_URL`.

**Server and accounts**
7. Prices: merge Portfolio#40 when its prod jobs are idle; set `NEWS_MARKET_SERVICE_KEY` in
   Portfolio, and `PORTFOLIO_MARKET_BASE_URL=http://portfolio-frontend`,
   `PORTFOLIO_MARKET_SERVICE_KEY`, `PORTFOLIO_MARKET_HOST` here; then `NEWS_MARKET_SOURCE=portfolio`.
8. Mobile app API: apply the `@mobile_api` block from `deploy/Caddyfile.snippet` to the
   shared edge Caddyfile; set `DRF_NUM_PROXIES=1` so throttles see real client IPs.
9. Store accounts: Cafe Bazaar, Myket, Google Play, Expo (EAS), and a safe upload keystore.
10. `NEWS_ALERTS_ENABLED=1` once the shadow eval passes.

**Decisions**
11. Contact address for `/privacy` and `/terms`; confirm the IP-log and backup-rotation lines.
12. Raw HTML archive (plan) vs storage policy (no second copies): currently dropped.
13. Backups: plan said Iran-only; the storage policy says none until a plan is approved.
14. Embeddings (paid) for grouping and storylines: off; storylines use watch items only.
15. Workbook mapping (evidence level → occurrence, Jev gold relevance → gold; gold *trend*
    left blank because Jev never predicts direction): confirm with the analyst team.
16. Portfolio keys for gold/fx (assumed `gold_18k`, `usd_irr`) and whether `interval=1h` exists.

**Needs a proxy abroad (deferred by decision)**: BBC Persian, Iran International, Radio
Farda, DW/Independent/Euronews Persian, GDELT, CME FedWatch, treasury.gov yields (FRED
used instead), Reuters/Bloomberg (licence). Stale at TGJU: WTI, copper, Nasdaq, Dow, Nikkei.

## Build status

Phases 1–6 of the plan are built and deployed (PRs #16–#29, 2026-10-02/03), except the
Portfolio side of Phase 4 (Portfolio#40, open). Still open by design: a three-worker split
(waits for server capacity), TypeScript migration of the web app (deferred), anything
behind the proxy abroad (Phase 7).
