# Verification evidence

## Current local results

| Check | Result | Limitation |
| --- | --- | --- |
| Frontend unit suite | PASS, 12 tests | Node's VM-module warning is expected. |
| Frontend production build | PASS | Covers the current uncommitted frontend tree. |
| Controlled rendered invalid Feed/Market/Ops routes | PASS | Uses a local synthetic API returning 400; no production data or mutation. |
| Controlled Article malformed/missing UI | PASS | Renders the existing not-found UI. |
| Live Market at 390px | PASS | No page-level horizontal overflow; other responsive routes were not rechecked. |
| Backend Ruff | PASS | Backend was unchanged by this audit. |
| Django system check | PASS | Does not substitute for the database test suite. |
| Fresh backend database suite | BLOCKED | PostgreSQL on `127.0.0.1:55432` is unavailable. |
| Live disposable-account signup and feed session | PASS | The account was created and redirected to its authenticated feed; no real identity data was supplied. |
| Live disposable-account review authorization | FAIL (fixed locally) | The current deployed SHA exposed a real shared review case with approve/skip controls to the non-staff account. No mutating button was used. |
| Current committed CI | PASS | GitHub CI `34712380694`, SHA `0569caa`. |
| Current committed deployment workflow | PASS | GitHub Deploy `34712380653`, SHA `0569caa`. |
| Direct VPS parity | PASS | Both image tags equal `0569caa`; compose services healthy; internal health 200. |
| Current production backup readback | PASS | Latest 35.8 MB archive completed `pg_restore --file=/dev/null`. |
| Release CI for `1304469` | PASS | GitHub CI `34740032943`; frontend, images, and PostgreSQL-backed backend suite passed. |
| Release deployment for `1304469` | PASS | GitHub Deploy `34740032951` completed, then direct VPS image/health inspection passed. |
| Release CI for `f9001ac` | PASS | GitHub CI `34740197939`; frontend, images, and PostgreSQL-backed backend suite passed. |
| Release deployment for `f9001ac` | PASS | GitHub Deploy `34740197935`; direct VPS inspection found both images pinned to this SHA and all services healthy. |
| Deployed synthetic account workflow | PASS | Signup, authenticated feed, staff-route denial, clean login, and server-side sign-out were verified. |

## Scope control

Temporary synthetic local API and frontend processes were stopped after route verification.
A disposable account was created with explicit authorization, but no article, review, A/B
judgment, export, production configuration, or service state was modified. Its token was
revoked by the tested sign-out route; the account itself was not deleted.
