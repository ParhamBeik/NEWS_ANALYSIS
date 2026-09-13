# Evidence ledger

## Browser session

- Existing Codex in-app browser tab 1 was reused at `https://news-89-106-206-4.sslip.io/`.
- The session was authenticated as the existing staff user `parham`; cookies, local storage, saved passwords, and session stores were not inspected.
- The original tab was restored to the Feed after each read-only route check.
- Browser console error/warning collection was empty for the inspected normal routes.
- Visual/accessibility evidence captured in-session included the Feed, Review queue, Market, Operations, Exports, and Django admin user list. The meaningful Market discrepancy was visible simultaneously in the metric card and outcome rows.
- Shared-shell check: Feed, A/B lab, Review, Quality, Market, Ops, and Exports links were present; Feed carried `aria-current="page"`; Skip to content targeted the focusable `main` region. No navigation or mutation was triggered by this check.
- Refresh check: reloading the live Feed retained the route, `Analyst feed`, signed-in user `parham`, and the staff-only Admin link.

## Live data consistency observations

- Feed observation: 3,659 fetched in 24 hours, 9 analysed, 2 flagged notify, `$0.0000` spend, and 30,232 matching stories.
- Operations observation: 31,277 fetched, 29,072 canonical, 371 classified, 154 evaluated, 2,205 duplicates collapsed, 10 unresolved dead letters, and five retained verified backups.
- Operations control observation: `/ops?days=7` rendered “Last 7 days” and marked the 7d range link active; the tab was restored to Feed.
- Quality observation: 2 approved human labels, 0/0 category comparison, 50.0% directional accuracy over 60 scored predictions, and 84 unscored neutral/uncertain predictions.
- A/B observation: one active control variant, three inactive challengers, no pairs, and no judgements.
- Exports observation: nine files listed; a protected 18 KB TXT download produced a browser download event without navigation away from the page.
- Provider state: Feed and Operations both reported inference paused because the provider wallet has no usable quota.

## Boundary and error evidence

- Empty login submission produced browser-required-field validation.
- Synthetic sign-up mismatch produced `Passwords do not match.` without creating an account.
- Feed no-result search returned `0 stories match` and a clear empty state.
- Feed checkbox filters produced `?unanalysed=true` and `?include_duplicates=true`; the duplicate view rendered `32,452 stories match`. The tab was restored to the unfiltered Feed afterward.
- Normal unknown-page navigation rendered the product not-found state.
- Invalid `notify`, `symbol`, `days`, and article-ID inputs rendered generic error references rather than field-specific validation; tracked as UX-001.
- The malformed `notify` route rendered a Feed-unavailable panel with one Retry button; clicking Retry refreshed the same invalid request and left the generic error visible, then the tab was restored to Feed.
- Unauthenticated HTTP requests redirected `/review` to `/login` and `/admin/` to Django admin login.
- Pre-submit identifier check: the authenticated admin user search for `codex-e2e-20260912-2246` returned `0 users` out of 6 total; the tab was restored to Feed.
- Live header probe: `curl -skI https://news-89-106-206-4.sslip.io/login` returned HTTP/2 200 with CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, Permissions-Policy, and Referrer-Policy; no `Strict-Transport-Security` header was present. Tracked as SEC-001.
- Review interaction check: category, one score axis, and trend selections changed to their selected visual states; Approve and Skip remained unsubmitted.

## Local verification

- Baseline before edits: `0569caa54c7b6d25a273e29630b28090a7be184f` on `main`, matching `origin/main`; the initial worktree was clean.
- Local change: `frontend/app/market/page.js` now counts only rows whose `direction_correct` is not null.
- Regression test: `frontend/tests/dashboard.test.mjs`.
- `npm test`: 10 passed, including malformed-query boundary coverage.
- `npm run build`: passed after the Market and query-boundary fixes.
- Ruff: passed.
- Django pytest: blocked during database setup because PostgreSQL at `localhost:55432` refused connections; no test result was treated as a pass.
- Current environment recheck: `pg_isready -h 127.0.0.1 -p 55432` reported no response; `docker compose -f deploy/docker-compose.dev.yml ps` could not connect because the local Docker daemon is not running. No service was started.
- No deployment, push, migration, restart, or VPS write occurred.
- Live post-fix recheck: `/?notify=not-a-valid-verdict`, `/market?symbol=invalid`, `/ops?days=not-a-day`, `/article/not-a-number`, and `/article/999999` all still showed the pre-deployment generic error behavior; the browser tab was restored to Feed.
- Visual evidence: a full-page in-session capture of live `/market?symbol=invalid` showed the generic “This page failed to render” panel and Retry control. It was not written to disk because the full shell includes the existing account name.

## Deployment evidence limitation

Local deployment metadata identifies `/opt/apps/news-intel` and the live hostname, and the workflow requires a secret SSH host. The objective supplied no SSH host or alias, so deployed SHA, service health, logs, and local/live parity remain unverified.
