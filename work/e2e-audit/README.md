# End-to-end audit

Status: **INCOMPLETE — awaiting confirmation immediately before isolated account creation.**

- Audit timestamp: 2026-09-12T22:46:12+03:30.
- Application: `https://news-89-106-206-4.sslip.io/`.
- Browser evidence: existing Codex in-app browser tab, authenticated admin user `parham`.
- Local baseline before the audit: `0569caa54c7b6d25a273e29630b28090a7be184f` on `main`, matching `origin/main`; the worktree was clean.
- VPS inspection: blocked because the objective supplied no SSH host or alias. No SSH, deployment, service restart, migration, database write, push, or deployment was attempted.
- Account safety: no new account or synthetic record was created. No credentials, tokens, cookies, or personal data were stored here.
- Responsive testing: the browser viewport capability did not honor widths below approximately 1280px; normal-viewport overflow was checked, but narrow-breakpoint coverage remains blocked by tooling.
- Backend tests: blocked by the unavailable local PostgreSQL service at `localhost:55432`; a current `pg_isready` check still reports no response and the local Docker daemon is unavailable. This is an environment limitation, not a passing result.
- Live header probe: the expected CSP and related hardening headers were present on `/login`, but HSTS was absent; see SEC-001. The shared edge policy was not changed.
- Local query-boundary remediation now gives Feed, Market, and Operations contextual validation and routes invalid Article IDs to not-found. The live recheck still showed the old generic errors because this change was not deployed.
- Frontend tests, production build, and Ruff passed after the local Market metric and query-boundary fixes. Both fixes are local only and are not deployed.

## Inventory boundary

Source and rendered UI discovery agree on these primary application routes: `/`, `/article/[id]`, `/review`, `/ab`, `/kpi`, `/market`, `/ops`, `/exports`, `/login`, and `/signup`. The logout form route and protected export-download route were also traced; loading, error, and not-found boundaries were exercised through normal and malformed navigation. `robots.txt` is metadata-only, and `/admin/` is the separately served Django admin surface.

The backend surfaces behind the UI were traced through health/auth/me, feed statistics, articles, sources, runs, variants, reviews, A/B pairs, KPI, market, operations, export listing, and export download endpoints. Direct anonymous boundary checks covered protected application and admin routes.

See [coverage-matrix.md](coverage-matrix.md), [findings.md](findings.md), and [performance.md](performance.md).
