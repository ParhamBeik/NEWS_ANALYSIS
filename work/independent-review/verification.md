# Verification evidence

## Automated checks run on 2026-09-19

| Command/check | Result |
|---|---|
| Focused frontend server-helper tests | Passed. |
| Focused backend authorization and scheduler tests against PostgreSQL | Passed. |
| `make ci` | Passed: Ruff, Django check, strict deploy check, migration drift, 427 backend tests, 14 frontend tests, and production frontend build. |
| `backend/.venv/bin/python -m unittest discover -s deploy/tests -v` | Passed: 2 shell integration tests, including fail-then-retry backup behavior. |
| `pip-audit -r backend/requirements.txt` | Passed: no known vulnerabilities. |
| `npm audit --omit=dev --audit-level=low` | Passed: zero vulnerabilities. |
| `git diff --check` | Passed. |
| `graphify update .` | Completed: repository graph refreshed after source changes. |
| System, Cloudflare, Google, and Quad9 DNS probes | Every query was intercepted to `10.10.34.36`; normal HTTP/HTTPS timed out. |
| Direct-IP Google and Cloudflare DNS-over-HTTPS probes | Both TLS connections were reset by the network. |
| Resolution from the Iran VPS | Correctly returned `45.139.10.12`, isolating the wrong answer to the client ISP path. |
| Forced-IP HTTP/HTTPS and TLS SNI probe | HTTP/HTTPS answered; TLS 1.3 negotiated with an untrusted Caddy Local Authority certificate. |

On 2026-09-20, an additional PostgreSQL integration test passed after seeding the exact legacy
weekly cron row and asserting that schedule setup retains its identity, clears the cron, and
assigns an hourly interval. This proves the deployed-row conversion path, not only fresh install.
The complete `make ci` gate passed again after this change: Ruff, Django checks, strict deployment
check, migration drift, the full backend suite, 14 frontend tests, and the production build.
No tests were skipped or deselected. Workbook tests still emitted openpyxl warnings about removed
conditional-formatting and data-validation extensions; this is a fidelity risk for edited source
workbooks, not a failure of this scheduler change. Test settings also lack a staticfiles directory.
At a fresh read-only VPS check at 2026-09-20 18:16Z, the same backend/frontend image SHA was
healthy and the provider circuit had closed at the weekly probe's 00:30Z run. This is evidence of
natural recovery, not evidence that the local hourly correction was deployed.

An additional PostgreSQL API integration check reproduced a gold outcome in a dollar-symbol
response (failure on the pre-fix query), then passed when outcomes were scoped to the requested
symbol. This tests the serialized API boundary, not a rendered Market screen. The full gate was
rerun after this correction and passed: Ruff, Django checks, strict deployment check, migration
drift, the full backend suite, 14 frontend tests, and the production build. No test was skipped.

The backend suite used the repository's PostgreSQL/pgvector and Redis services, not SQLite. No
tests were skipped or deselected in the recorded full run.

The final focused rerun first failed because Docker Desktop and PostgreSQL had stopped. After the
same development services were restored healthy, 7 focused backend cases, all 14 frontend cases,
both backup shell tests, and the diff-integrity check passed. The initial refusal is classified as
an environment interruption, not a code pass or failure.

## Browser and rendered UI

- Historical browser artifacts were recovered and treated as leads, not current proof.
- The connected Chrome capability failed before a usable tab/session was available. Its own
  troubleshooting path also failed, so the skill's rules prohibited switching to unrelated
  browser automation.
- The production hostname resolved to `10.10.34.36` instead of the VPS. Direct queries nominally
  sent to `1.1.1.1`, `8.8.8.8`, and `9.9.9.9` returned the same sinkhole, showing network-level DNS
  interception rather than a local resolver typo. Direct-IP TLS attempts to Google and Cloudflare
  DNS-over-HTTPS were reset, independently reproducing selective ISP anti-bypass filtering. The
  VPS resolved the same hostname correctly to `45.139.10.12`. Forcing that app mapping reached
  HTTP and HTTPS, proving the app's own SNI route can answer, but TLS presented an untrusted Caddy
  Local Authority certificate.
- Consequently, changed staff/non-staff screens, invalid-query presentation, logout, refresh
  persistence, narrow responsive breakpoints, accessibility, console errors, and network timing
  are **NOT TESTED in the current review** through the real public client path.
- No synthetic production account or production record was created or changed.

## Performance

- No repeatable previous benchmark, sample distribution, or declared budget was recoverable.
- Historical settled browser page samples were Feed 757/734/643 ms, Operations
  1255/1265/1244 ms, and Market 885/705/803 ms; one category-filter sample was 457 ms. These
  are leads from the prior audit, not independently repeated current measurements.
- Five forced-IP `/login` samples returned HTTP 200. Median total time was 27 ms over HTTP and
  58 ms over HTTPS; median time-to-first-byte was 22 ms and 46 ms respectively. The first HTTP
  request was a 392 ms cold outlier.
- Those figures bypass DNS, ignore certificate trust, and do not include browser render time. The
  real hostname path timed out before connection, so they prove origin responsiveness only.
- No production load or concurrency test was run because it was not authorized.
- Rendered responsiveness and real Iranian public-path performance remain **NOT TESTED**, not
  passes.

## Final diff review

- The aggregate source diff is limited to five root-cause corrections and a regression check for
  each changed behavior.
- No new abstraction or dependency was introduced.
- The persisted periodic-task name was deliberately retained so deployment updates the existing
  row instead of enabling a duplicate schedule. The regression test now seeds that legacy row.

## September 24 readiness continuation

- Local branch `review/independent-e2e-remediation` remains dirty and unpublished. The live
  frontend is `87fddf5`; the backend and workers run a separate local `newsintel-backend:patch`
  image built September 22. The VPS checkout is `67a98fa` with unrelated dirty deploy files.
  The patch's three inference files were compared with the local tree before integration.
- Read-only VPS sample: 72,909 articles; 44,155 canonical articles fetched in 14 days;
  1,118 evaluations; 3,887 embeddings. The sole active variant uses no memory. Its live
  scheduler runs crawl every five minutes and explicitly removes `embed-missing`; the local
  schedule and release gate now retain those choices. The provider budget circuit is open,
  with no node events in the last 24 hours; no credit or production record was changed.
- Eight staff-level APIClient reads per endpoint against the running backend: `/api/ops/`
  median 2,475 ms, maximum 6,329 ms; articles 64 ms, KPI 27 ms, Market 39 ms, exports 3 ms
  median. Three repeated notify queries took 718, 706, and 644 ms. The same verdict set
  counted in one pass took 657 ms with identical state counts (197, 547, 0). The local shared
  helper now uses one pass. Replacing the 44,155-ID list with an Article queryset returned
  those same counts in a five-run median of 18.8 ms (16.5–62.6 ms) on the running backend.
  The local helper now uses the queryset; the deployed endpoint remains unmeasured after the fix.
- The shared 8 GB VPS had 7.4 GB free on a 99 GB root filesystem (93% used), 2.1 GB
  available RAM and 2.8 GB used swap. The crawl worker used 585 MiB of its 640 MiB limit,
  with one cgroup OOM kill; its four child processes used roughly 140–160 MB RSS each.
  Crawl/default/inference queue depths were all zero, and 3,587 articles were fetched in
  24 hours. Local Compose reduces crawl concurrency from four to two; post-release memory
  and queue behavior still need measurement. This app's database and backup volumes used
  about 439 MB and 403 MB; no shared disk cleanup was performed.
- The newest local dump was 85 MB from September 23. No off-host target or marker is
  configured, and no restore rehearsal was possible. The configured hostname
  `news.parhambm.ir` resolved to `45.139.10.12` and returned trusted HTTPS `/login` 200
  from this workstation and the VPS; authenticated browser workflows remain untested.
- Local `make ci` passed after the new query and schedule changes: 434 backend tests,
  14 frontend tests, Ruff, Django checks, migration drift, and frontend build. Backup
  shell tests (3), dependency audits, Compose validation, and backend image build passed.
  Backend source-only coverage was 75% (3,451 statements, 858 missed); the aggregate
  diff was reviewed against `main` and passed `git diff --check`. No commit, push,
  CI run for this tree, deployment or live post-change check.
