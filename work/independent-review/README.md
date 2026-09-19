# Independent review

Verdict: **PARTIALLY VERIFIED** as of 2026-09-19.

The previous browser/remediation work was recovered from commits and deleted audit artifacts.
Its reported UI, validation, authorization, logout, and market-counter defects were real, and
the corresponding fixes are present in the current deployed revision. The review was not
conclusive, however: current rendered browser workflows could not be repeated because the
connected-browser bridge was unavailable; no usable performance measurements existed; four
locally correctable defects and one external ingress blocker remained.

## Findings

1. **High — the new Iran VPS is not reachable through a normal trusted public hostname path.**
   The obsolete VPS is out of commission. The VPS itself resolves the new hostname correctly, but
   the Iranian client path rewrites it to `10.10.34.36` and resets direct TLS attempts to public
   DNS-over-HTTPS resolvers. Forcing the correct app IP reaches TLS, but exposes Caddy's private CA
   certificate while the repository edge template expects public ACME TLS.
2. **High — authorization tests could pass while regular users regained staff-only access.**
   The shared authenticated fixture had been promoted to staff, so most endpoint tests no longer
   exercised ordinary-user permissions. The fixture is regular again, staff-only tests use an
   explicit fixture, and all Review and A/B read/write actions now have denial coverage.
3. **High — inference recovery could remain paused for almost an extra week.** The state machine
   owned an exact `next_probe_at`, while a fixed weekly scheduler independently decided when to
   call it. Production was overdue since 2026-09-13. The existing periodic row now polls hourly;
   the persisted due time remains authoritative.
4. **High — a transient database startup race could skip the day's backup.** After the
   2026-09-18 host restart, the backup container attempted before PostgreSQL was ready and then
   slept for 86,400 seconds. Failed dumps now retry after 300 seconds; successful dumps retain
   the daily interval.
5. **Medium — a staff API outage was presented as a signed-out session.** The root layout must
   tolerate identity lookup failure, but staff authorization guards must preserve a 5xx response.
   The staff guard now uses the strict API path, while 401 still redirects to sign-in.

## Completion boundary

- Locally fixed and fully test-verified: findings 2–5.
- Committed locally on `review/independent-e2e-remediation`: findings 2–5 and this evidence package.
- Pushed, deployed, or live-verified: none of this review's corrections.
- The application stack on the new VPS is internally healthy at `87fddf5`, but normal public DNS,
  trusted TLS, and Iran-ISP reachability are blocked. It also contains the provider-scheduling and
  backup-retry defects until a release is authorized.
- Current browser interaction, responsive behavior, accessibility, and latency remain **NOT
  TESTED** because the required connected-browser capability was unavailable.
- Two decisions remain: supply the intended real hostname/ingress strategy for trusted TLS, and
  authorize commit/push/deployment of the verified local corrections. Until then the review cannot
  complete browser or live-path verification.
