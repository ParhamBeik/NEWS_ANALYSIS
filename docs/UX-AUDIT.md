# UX audit: news.parhambm.ir (2026-10-03)

Walked on the live site at `e89e9bf` as a staff user and as a signed-out visitor, at
375 px (phone), 800 px and 1280 px (desktop). Severity: **B** blocker, **D** wrong data,
**F** friction, **P** polish. Status column is filled as fixes land.

Context that colours most of the reader experience: AI decisions are stalled (every Jev call
is refused by the budget guard, $0 spent), so no event has a score, tier, brief or
translation. The UI has to look good in that state too, not only when AI is healthy.

## Findings

| # | Sev | Where | Finding | Root cause / fix | Status |
|---|---|---|---|---|---|
| F1 | D | Radar | Undated items (IAEA feed has no dates) jump back to "just now" on every crawl and pin the top of the radar | `articles/ingest.py` refreshes `fetched_at` on every re-see; `core/events.py` falls back to `fetched_at` for `event_time`. Fall back to first-seen `created_at` | fixed (`core.events.reported_at`) |
| F2 | D | Radar | 0 of 50 events show a photo, including cleared outlets (ISNA, IRNA) | Not diagnosed: `publishable_image` logic is right; check image download stats | open |
| F3 | D | Event page | An aggregator's copy (Shahr-e Khabar relaying Eghtesad Online) counts as a second independent group, so evidence reads «منابع مستقل»; the copy is shown under the origin's name | `core/events.py` `evidence_level` counts aggregator groups; the UI omits "via" | evidence fixed (aggregators add no group); "via" open |
| F4 | F | Event page | Three separate "being assessed / not ready" messages when AI has not run | Collapse into one pending line | open |
| F5 | P | Event page | English "Staff: takedown" label in the Persian page | Translate | open |
| F6 | P | Event page | Browser tab title is "News Intelligence", not the headline | `generateMetadata` | open |
| F8 | F | All, phone | Sticky header is 155 px (19 % of the screen); 11 nav links wrap to 3 rows; tap targets 16–28 px | Bottom tab bar + staff menu + account menu (claude.ai batch-3 draft) | open |
| F9 | D | Radar | Persian headlines carry the «انگلیسی» tag | `lib/reader.js` `untranslated()` treats "no AI translation" as English; use the source language | fixed |
| F10 | F | Radar, phone | No story above the fold: title, intro, two pill rows and a banner come first | Compact header, one filter row | open |
| F11 | F | Radar | "43 of 44 sources updated" banner shown to readers at 98 % coverage | Show only when coverage is really degraded; detail stays on /ops | open |
| F12 | F | Event market | Asset tabs run off-screen with no scroll cue; prices in rial labelled "(IRR)" | Wrap or fade edge; Toman with Persian unit | open |
| F13 | P | /market | English fragments ("TGJU · IRR · observations", "1W 1M", raw "1"); flips to dark theme | Translate; reader theme | open |
| F14 | B | /market, phone | Chart canvas absent after 8 s on 2 of 3 loads, no console error | Reproduce locally | open |
| F15 | F | /macro | Every policy rate "—", prices "not connected": an empty page in the main nav | Hide from nav until Portfolio is connected | open |
| F16 | F | Onboarding / watchlist | ~165 unordered chips; save button at the very bottom; "pick 3" only enforced after submit | Sticky bar with count + save; popular items first | open |
| F18 | P | /ops | English KPI tiles beside Persian panels; untranslated "title", "closed"; Gregorian dates | One language per page; Jalali | open |
| F19 | B | /ops | AI fully stalled (41,144 budget refusals today) but nothing says so; circuit "closed" reads as healthy | Top-of-page health banner | open |
| F20 | F | Crawl | State Department source blocked 558 times in 24 h, retried with no backoff | Back off or pause a source after repeated blocks | open |
| F21 | P | /ops | Funnel still shows the disabled classify/evaluate pipeline (1 %) | Remove or label as retired | open |
| F22 | F | Swipe review | "Nothing to review" without saying the AI is stalled | Explain the cause in the empty state | open |
| F23 | F | Nav | Classification / Evaluation / Articles belong to the retired pipeline; English labels | Move under a staff menu; drop retired pages from nav | open |
| F24 | F | /signup | English-only legacy staff signup beside the Persian phone login | Persian copy; decide which path readers use | open |
| F25 | B? | /login | Phone sign-in may answer `sms_unavailable`, so readers could not sign in | Verify the SMS provider configuration; hide the phone form when SMS is unavailable | open |

Retracted while auditing: F7 (wrong query parameter, not a bug), F17 (/inbox renders fine).

## Not yet covered

English mode end to end, light theme, tablet width, exports download, takedown action
(changes production data, so not exercised), PWA install.
