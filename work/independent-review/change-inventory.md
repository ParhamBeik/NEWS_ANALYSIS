# Reviewed change inventory

## Prior task, uncommitted

- Feed, Market, Operations, and Article pages: map validation failures to a contextual
  recovery state or the existing not-found boundary.
- Shared frontend API module: retain HTTP status in `ApiError` so routes can distinguish a
  validation response from an operational failure.
- Shared primitives: add the accessible query-error panel.
- Market page: count only outcomes whose directional result is non-null.
- Dashboard test: originally asserted source text only.
- `work/e2e-audit/`: prior task's audit artifacts.

## This independent review

- Moved the server-module VM loader to a shared test helper and added behavioral unit tests
  proving 400 and 403 API responses retain route-usable status rather than redirecting a
  signed-in user to the login page.
- Restricted shared Review and A/B APIs to staff, hid those controls from non-staff
  navigation, and rendered an explicit staff-only state for direct route navigation.
- Added the independent-review records in this directory.

## Classification

All prior application changes are uncommitted, unpushed, undeployed, and present only in the
current worktree. The committed base and `origin/main` are both `0569caa`; the latest terminal
CI and deployment workflows also target that committed SHA, not these local changes.
