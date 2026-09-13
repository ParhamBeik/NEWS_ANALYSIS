# Findings

## M-001 — Market “Scored predictions” included unscored rows

- Severity: MEDIUM.
- Type: frontend logic / data presentation.
- Reproduction: open `/market` as admin and compare the `SCORED PREDICTIONS` card with the prediction-outcomes table.
- Expected: the card counts only rows with a scored directional verdict.
- Observed live at 22:46: the card showed `144`, while the same table contained `84` `not scored` rows for neutral or uncertain predictions.
- Local fix: compute the metric from rows where `direction_correct !== null` and add a source-contract regression test. This is local only; the live VPS still needs deployment and re-verification.

## UX-001 — Malformed query values expose generic server-error references

- Severity: MEDIUM.
- Type: frontend/backend boundary and usability.
- Reproduction: open `/?notify=not-a-valid-verdict`, `/market?symbol=invalid`, `/ops?days=not-a-day`, or `/article/not-a-number`.
- Expected: a clear validation message, safe default, or product not-found state explaining which value is invalid.
- Observed: generic “This page failed to render” error references; the feed additionally showed a frontend-container-log digest. Normal unknown-page navigation did render the product not-found state.
- Local fix: 400 API responses now render contextual query-error states for Feed, Market, and Operations; malformed or missing Article IDs use the existing not-found boundary. A source-contract regression test covers these routes.
- Live recheck after the local fix: all five malformed live routes still showed the old generic error behavior because no deployment occurred.
- Status: fixed in the worktree, unresolved on the live VPS pending deployment and re-verification.

## ENV-001 — Inference is paused by provider quota state

- Severity: HIGH operational blocker.
- Type: environment/provider availability.
- Evidence: Feed and Operations both displayed “Inference paused — classification is not running” and stated that the provider wallet has no usable quota. Operations showed 371 classified versus 154 evaluated over 14 days, 10 unresolved dead letters, and recent aborted runs.
- Status: explained environment condition, not treated as a passing functional result. Resolution requires an operator/provider action outside this audit’s authority.

## ENV-002 — Deployment identity and server inspection are unavailable

- Severity: HIGH audit blocker.
- Type: deployment/evidence limitation.
- Evidence: repository deployment files identify `/opt/apps/news-intel` and the live hostname but provide no SSH host or alias. The deployed commit, container image, service logs, and live/local SHA match could not be verified.
- Status: blocked pending a safe read-only SSH target.

## ENV-003 — Isolated mutation coverage is pending confirmation

- Severity: HIGH audit blocker.
- Type: test-data authorization.
- Evidence: no existing demo credentials were supplied; a read-only admin search confirmed `codex-e2e-20260912-2246` is not already present. The objective requires a pause immediately before submitting a new synthetic account and before any irreversible deletion.
- Status: paused at the required confirmation boundary. No account or synthetic record was created.

## ENV-004 — Narrow responsive testing is limited by the browser surface

- Severity: MEDIUM audit limitation.
- Type: tooling.
- Evidence: the in-app browser viewport override did not honor the requested 375px width and retained a desktop-sized viewport. Normal-viewport page-level overflow was absent and internal tables exposed scroll containers where needed.
- Status: blocked for narrow-breakpoint visual verification; no claim of mobile pass was made.

## SEC-001 — Live HTTPS response lacks Strict-Transport-Security

- Severity: LOW.
- Type: deployment/edge security headers.
- Evidence: `curl -skI https://news-89-106-206-4.sslip.io/login` returned HTTP/2 200 with CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, Permissions-Policy, and Referrer-Policy, but no `Strict-Transport-Security` header.
- Impact: first-time browsers are not instructed to enforce HTTPS for future visits, leaving a downgrade exposure before the browser has learned an HSTS policy.
- Recommendation: add HSTS in the shared Caddy `security_headers` policy after confirming every relevant hostname is HTTPS-only; enable preload only after a separate domain-readiness review.
- Status: unresolved because the shared edge configuration is outside this repository and VPS access was not supplied.
