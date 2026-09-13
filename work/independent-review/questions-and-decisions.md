# Questions and resolved decisions

## Resolved objectively from existing behavior

| Decision | Basis | Result |
| --- | --- | --- |
| Who may label reviews or submit A/B votes | Those actions alter shared training and experiment evidence; public signup creates ordinary non-staff users. | Both workflows require staff and non-staff users receive an explicit access state. |
| What to do with an authenticated 403 | A valid session must not be mistaken for an expired session. | Preserve the 403 as a structured error; staff-only pages make the authorization state explicit. |
| What to do with repeat sign-out | A cleared cookie must still reach the route handler. | Treat the logout route as middleware-public while retaining its POST-only handler. |

## Deliberately not decided or changed

| Item | Why it needs owner direction | Current state |
| --- | --- | --- |
| Provider wallet restoration | It may require purchasing or changing a third-party provider plan. | Inference remains paused; no financial or provider-account action was taken. |
| HSTS at the edge | The active hostname is an `sslip.io` address and edge policy is outside the repository; changing it needs hostname and TLS-policy review. | Existing CSP, frame, MIME, permissions, and referrer headers remain present; HSTS remains absent. |

No product, compatibility, data-retention, or architecture preference was needed for the code
changes made in this review.
