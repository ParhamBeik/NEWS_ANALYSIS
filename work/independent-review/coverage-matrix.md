# Browser coverage reconciliation

The 36 rows below preserve the prior audit's inventory. “Historical” is the prior task's
observation, not an independent current browser pass. The connected-browser bridge was unavailable
in this review; every rendered workflow still needs a fresh check on a trusted public path.

| Surface or workflow | Historical | Independent review / remaining check |
|---|---|---|
| Login screen | Pass | Source and build reviewed; rendered recheck blocked. |
| Empty login submission | Pass | Rendered validation recheck blocked. |
| Sign-up screen | Pass | Rendered recheck blocked. |
| Sign-up mismatch validation | Pass | Rendered recheck blocked. |
| Successful sign-up | Blocked | Later task created a synthetic non-staff account; this review made no account and cannot repeat the flow. |
| Logout / session persistence | Not run | Later task observed the redirect loop and fixed it; rendered recheck blocked. |
| Feed refresh / session persistence | Pass | Rendered refresh recheck blocked. |
| Global navigation and skip link | Pass | Rendered keyboard/accessibility recheck blocked. |
| Feed baseline | Pass | Rendered recheck blocked. |
| Feed source/category filters | Pass | Prior 457 ms category sample is historical; rendered recheck blocked. |
| Feed unanalysed/duplicate filters | Pass | Rendered recheck blocked. |
| Feed search empty state | Pass | Rendered recheck blocked. |
| Feed pagination | Pass | Rendered recheck blocked. |
| Feed malformed verdict query | Partial | Error handling reviewed and frontend tests passed; rendered recheck blocked. |
| Feed error boundary and Retry | Partial | Boundary and contextual 400 handling reviewed; rendered recheck blocked. |
| Article detail, unclassified | Pass | Rendered recheck blocked. |
| Article detail, evaluated | Pass | Rendered recheck blocked. |
| Article not-found | Pass | Rendered recheck blocked. |
| Article malformed/missing ID | Partial | Boundary behavior reviewed; rendered recheck blocked. |
| Review queue | Read-only pass | Staff authorization integration tests pass; rendered and mutation rechecks blocked. |
| Review selection controls | Read-only pass | Rendered selection and submission rechecks blocked. |
| A/B lab | Read-only pass | Staff authorization integration tests pass; rendered and judgement rechecks blocked. |
| Quality/KPI | Pass | Rendered recheck blocked. |
| Market | Pass with local fix | Counter computation and frontend check reviewed; rendered and data-consistency rechecks blocked. |
| Operations | Read-only pass | Production circuit independently inspected; rendered recheck blocked. |
| Operations date range | Read-only pass | Rendered filter recheck blocked. |
| Exports | Read-only pass | Rendered listing/download recheck blocked. |
| Django admin | Read-only pass | Rendered recheck blocked. |
| Admin user search/filter | Read-only pass | No account or permission was changed; rendered recheck blocked. |
| Anonymous protected-route boundary | Pass | Prior HTTP redirects corroborated; real browser recheck blocked. |
| Security response headers | Partial | Edge headers independently probed; HSTS absent and public TLS untrusted. |
| Existing demo-account discovery | Partial | Historical names are not credentials; no existing account was used. |
| User-owned CRUD | Blocked | No isolated synthetic record lifecycle was independently tested. |
| Authorization across demo/admin users | Blocked | Later task found non-staff access; local integration tests now enforce 403 for protected actions, browser recheck blocked. |
| Safe delete/archive/restore | Blocked | No synthetic record lifecycle was independently tested; no deletion performed. |
| VPS commit/service/log comparison | Blocked | Read-only new-VPS inspection now confirms deployed SHA, healthy internal services, and backup/probe defects. |

Automated checks establish source behavior at component boundaries, not rendering or client-side
navigation. The earlier “pass” labels cannot be promoted to current browser passes by this matrix.
