# Findings

## Fixed: test assurance was weaker than the behavior it claimed

The added dashboard checks matched source text, so a compile-valid semantic regression could
still pass. The test now executes the actual API module with a controlled 400 response and
asserts that route code receives `ApiError` with the expected status and path. This is a unit
check of the shared API boundary; the controlled rendered probes cover the route integration.

## Fixed and deployed: a public signup could alter shared evaluation evidence

The disposable non-staff account created during this review could open the live Review queue
and was presented Approve label and Skip controls for a real pending case. Neither action was
submitted, so no production label changed. Review labels feed both
quality reporting and retrieval memory; A/B votes are also shared experiment evidence. Both
viewsets now require staff, and non-staff navigation/direct pages provide a clear access state
instead of a misleading login redirect. The current release CI passed its PostgreSQL suite and
the live disposable account now receives the staff-only state for both workflows.

## Fixed and deployed: repeat sign-out could leave a bad login destination

The first sign-out correctly revoked the disposable session, but a second immediate request
without a cookie was intercepted as a protected `/logout` navigation and produced
`/login?next=/logout`. The logout route is now public to middleware while retaining its own
POST-only handler. A regression test locks that routing boundary, and the deployed account
completed a clean sign-in followed by server-side sign-out back to `/login`.

## Open: local fixes are not deployed

Fresh live checks still show the generic error panel for invalid Market and Article URLs. The
live Market page still reports 144 scored predictions while exposing 84 unscored rows. The
local fixes are correct but must not be represented as live fixes.

## Open external blocker: provider quota pauses inference

The authenticated Operations page still reports that inference is paused. This is a provider
availability condition, not a passing pipeline result and not safely repairable in this
repository without operator authority.

Read-only VPS inspection confirms this is not a scheduler failure: the circuit is
`open_budget` with a budget error kind, the configured retry delay is seven days, and the
enabled `weekly-circuit-probe` task is present. Restoring credit is the only safe path that
can close the circuit; the scheduled probe will then reopen inference automatically.

## Verified: committed release parity and backup readback

Read-only VPS inspection confirms backend and frontend image tags both equal `0569caa`, all
services are healthy, internal health returns 200, recent backend/frontend logs contain zero
error-pattern lines, and the latest 35.8 MB archive passes `pg_restore --file=/dev/null`.
This evidence applies to the prior committed release. The current release separately confirms
the new image pins, healthy services, and internal health.

## Open external finding: HSTS remains absent

The current live `/login` response has CSP, frame, MIME, permissions, and referrer policies,
but no `Strict-Transport-Security`. The shared edge policy is outside this repository.

## Observation: dynamic Article not-found responses stream as HTTP 200

The local Article routes render the correct not-found UI for malformed and missing IDs, but
their streamed HTTP response remains 200 after the authenticated layout begins. A global
unknown route returns 404. Changing the Article metadata path only duplicated an API fetch and
did not change that framework behavior, so it was not retained. This is a low-severity HTTP
semantic limitation for an authenticated surface, not evidence that the visible recovery is
broken.
