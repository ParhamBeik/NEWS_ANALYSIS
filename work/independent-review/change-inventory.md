# Reviewed change inventory

## Baseline and attribution

- Previous-task baseline: `0569caa54c7b6d25a273e29630b28090a7be184f`.
- Previous-task remediation: `13044694482f1a8e9726b8dc9aed502361e09e54` and
  `f9001acfb6b2b34eb831b98bcd01db80dce1bc94`.
- Both commits are ancestors of current `main` and were pushed, deployed, and later followed by
  the deployment-gating fix `1d83dd34ee92643add21b32265d952434e257f34`.
- Current baseline: `main == origin/main == 87fddf501601f60480bf7e441196ad79cded812d`.
- One worktree and one local branch exist; no background project writer was found.

## Previous-task changes reviewed

- Staff-only backend permissions for shared Review and A/B evidence.
- Staff-only frontend navigation and route guards.
- Typed API failures and contextual invalid-query recovery.
- Market scored-outcome counting.
- Logout redirect and middleware handling.
- Frontend/backend regression tests and removed audit artifacts.
- CI/deploy workflow execution and subsequent gating/rollback correction.

## Corrections in this review

| Area | Root cause | Minimal correction | State |
|---|---|---|---|
| Authorization tests | Default authenticated fixture silently became staff. | Restore ordinary user; add explicit staff fixture and all protected action checks. | Committed locally on the review branch. |
| Circuit recovery | Fixed weekly cron duplicated the persisted due-time decision. | Reuse the deployed task name but persist it as an hourly interval. | Committed locally on the review branch. |
| Backups | Any dump failure used the success interval. | Separate five-minute failure retry from daily success interval. | Committed locally on the review branch. |
| Staff route failures | Permissive layout identity helper collapsed API outage into logout. | Use strict API lookup only in the staff guard. | Committed locally on the review branch. |
| Edge deployment guidance | The example still named the decommissioned VPS and an ISP-filtered wildcard DNS service. | Replace it with a neutral real-domain example and state the trusted-certificate requirement. | Committed locally on the review branch. |
| Scheduler upgrade test | A fresh-install assertion did not exercise the existing production cron row. | Seed the legacy row and prove in-place conversion to hourly. | Locally verified; included in the follow-up review commit. |
| Review evidence | Deleted prior artifacts obscured the audit trail. | Recreate a compact current evidence package. | Committed locally on the review branch. |

No migration, dependency, public API, schema, data, account, remote, or production mutation was
made. No unrelated refactor was included. The commit is local only and has not been pushed.
