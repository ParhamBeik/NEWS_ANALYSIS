# Coverage matrix

| Surface or workflow | Result | Evidence / limitation |
| --- | --- | --- |
| Login screen | PASS | Renders username/password fields, required attributes, autocomplete hints, and sign-in action. |
| Empty login submission | PASS | Browser validation reports “Please fill out this field.” without sending credentials. |
| Sign-up screen | PASS | Renders username, optional email, two required passwords, and an 8-character minimum. |
| Sign-up mismatch validation | PASS | Synthetic non-account data returned “Passwords do not match.”; no account was created. |
| Successful sign-up | BLOCKED | Objective requires confirmation immediately before final account creation; no demo account details were supplied. |
| Logout / session persistence | NOT RUN | Logging out would alter the existing admin browser session. |
| Feed refresh / authenticated session persistence | PASS | Reloading the live Feed retained the route, `Analyst feed`, signed-in username `parham`, and staff-only Admin link. |
| Global navigation and skip link | PASS | Seven primary links were present, Feed exposed `aria-current="page"`, and Skip to content targeted the keyboard-focusable main region. |
| Feed baseline | PASS | Authenticated feed rendered cards, metrics, source/category/verdict filters, search, checkboxes, and pagination. |
| Feed source/category filters | PASS | Source and category query parameters persisted after navigation; category filter settled in 457 ms and returned 88 stories at observation time. |
| Feed unanalysed/duplicate filters | PASS | Toggling the two checkbox controls produced `?unanalysed=true` and `?include_duplicates=true`; the duplicate view rendered 32,452 matching stories and the tab was restored afterward. |
| Feed search empty state | PASS | Synthetic search returned 0 stories and a clear no-results message. |
| Feed pagination | PASS | `offset=20` rendered rows 21–40 and newer/older navigation. |
| Feed malformed verdict query | PARTIAL | Live API error still surfaces a generic server-error reference; the local worktree now renders contextual validation. See UX-001. |
| Feed error boundary and Retry | PARTIAL | Live malformed-filter case rendered a Feed-unavailable panel with Retry; local code now handles the 400 before that boundary, but the fix is not deployed. See UX-001. |
| Article detail, unclassified | PASS | Article 32383 rendered title, image, Persian body, verdict empty state, and provenance. |
| Article detail, evaluated | PASS | Article 2 rendered classification/evaluation/summary and provenance. |
| Article not-found | PASS | Unknown page path rendered the product not-found state. |
| Article malformed/missing ID | PARTIAL | Live malformed and missing IDs still show generic errors; local code now routes them to the not-found boundary. See UX-001. |
| Review queue | PASS (read-only) | Queue item, model answer context, category/axis/trend controls, text areas, approve, and skip actions rendered. Mutation actions were not clicked. |
| Review selection controls | PASS (read-only) | Category, one score axis, and trend selections entered their selected visual states; Approve and Skip were not submitted. |
| A/B lab | PASS (read-only) | Empty-pair state, active/inactive variants, standings, bias, and setup instructions rendered. Judgement was not submitted. |
| Quality/KPI | PASS | Human-label, category, axis, notify, and gold back-test sections rendered with current values. |
| Market | PASS with local fix | Symbols, chart, snapshots, outcomes, and alternate symbol view rendered. Live metric mismatch fixed locally; see M-001. |
| Operations | PASS (read-only) | Funnel, budget, backup, source health, node outcomes, dead letters, prefilter, extraction tiers, and recent runs rendered. |
| Operations date range | PASS (read-only) | Selecting 7d changed the route to `/ops?days=7`, rendered “Last 7 days,” and marked the 7d control active. |
| Exports | PASS (read-only) | Nine files listed; a protected 18 KB TXT download event was observed. |
| Django admin | PASS (read-only) | Admin home rendered authenticated model links and recent actions. No add/change/delete controls were used. |
| Admin user search/filter | PASS (read-only) | Search for `demo` returned one candidate; the non-staff filter returned five candidate usernames. No user was selected or changed. Credentials were not inspected. |
| Anonymous protected-route boundary | PASS | An unauthenticated HTTP request to `/review` redirected to `/login`; `/admin/` redirected to Django admin login. |
| Security response headers | PARTIAL | CSP, X-Content-Type-Options, X-Frame-Options, Permissions-Policy, and Referrer-Policy were present on live `/login`; HSTS was absent. See SEC-001. |
| Existing demo-account discovery | PARTIAL | Read-only admin discovery found `demo-check`, `qa.news.check`, `qa.news.check2`, `qa.news.retest`, and `verify1789239193705`; no credentials are available, so none was used. |
| User-owned CRUD | BLOCKED | Requires isolated demo account and confirmation before account creation. |
| Authorization across demo/admin users | BLOCKED | Requires isolated demo account; admin was tested read-only. |
| Safe delete/archive/restore | BLOCKED | No synthetic records exist; no destructive action was attempted. |
| VPS commit/service/log comparison | BLOCKED | SSH target/alias missing from the objective. |
