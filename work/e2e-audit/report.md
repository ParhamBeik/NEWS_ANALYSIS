# Audit report — provisional

This report is intentionally provisional. The objective remains active because isolated demo-account mutations and VPS read-only verification are not complete.

## Coverage

The current matrix contains 36 inventory items. Thirty were exercised to a recorded result: 25 PASS/PASS-with-local-fix and 5 PARTIAL, for 83% exercised coverage. Six items remain BLOCKED or NOT RUN: successful signup, logout/session mutation, user-owned CRUD, cross-user authorization, safe deletion, and VPS deployment comparison.

This percentage describes the matrix rows only; it is not a claim that every individual control inside each row has passed.

## Verified

- Existing authenticated admin session was reused.
- All source-discovered frontend routes and the main API-backed dashboard surfaces were mapped to rendered routes.
- Feed filtering, empty search, pagination, article detail, Review, A/B, Quality, Market, Operations, Exports, admin, login, signup validation, protected redirects, download behavior, normal-viewport overflow, and settled latency were exercised.
- The Market metric defect was reproduced and fixed locally with regression coverage.

## Blocked or at risk

- The live provider quota state pauses inference and leaves dead letters/recent aborted runs.
- No safe SSH target was supplied for deployed-version, service, log, and parity verification.
- Existing non-admin candidate usernames were found, but credentials are unavailable. No password guessing or secret inspection is permitted.
- Narrow responsive testing below the browser’s effective desktop viewport floor was not possible.
- Backend tests require local PostgreSQL/pgvector and could not start.
- Malformed query values still expose generic error references on the live VPS. The worktree contains a tested contextual-error/not-found fix, but it is not deployed or live-verified.
- The live HTTPS response is missing HSTS while other checked security headers are present; this remains an unresolved low-severity edge finding because the shared policy is outside local scope.

## Next authorized action

Before the final account-creation submission, obtain action-time confirmation. Then use only the isolated account and synthetic `codex-e2e-*` records for review/A-B mutation, persistence, permission, duplicate-submission, and safe-delete checks.
