# Browser verification evidence

- A fresh authenticated in-app-browser check of `/market?symbol=invalid` showed the live
  generic failure panel, not the local contextual recovery panel.
- A fresh authenticated check of `/article/not-a-number` likewise showed the live generic
  failure panel.
- A fresh authenticated Operations check still contained the inference-paused condition.
- A disposable non-staff account was created and reached the authenticated Feed with a
  persistent session. It could also open `/review` and received a real case plus Approve
  label and Skip controls. No mutating review action was selected; this is the evidence for
  the locally fixed staff-only authorization defect.
- After deployment, the same account's navigation contained neither Review nor A/B lab.
  Direct `/review` and `/ab` navigation rendered explicit staff-only states. It also saw the
  deployed Unknown market symbol recovery and Article not-found state.
- The account completed a clean sign-in and sign-out. A subsequent protected navigation
  reached `/login` without a poisoned `next=/logout` target, demonstrating server-side token
  revocation and the repeat-sign-out middleware correction.
- A fresh authenticated Market check showed `SCORED PREDICTIONS 144` and 84 `not scored` rows.
- A fresh 390px live-Market check reported an effective 390px viewport, 375px root/body scroll
  widths, and no page-level horizontal overflow. The viewport was reset immediately afterward.
- The full prior browser matrix, remaining responsive surfaces, and latency sample were not
  repeated. They are classified as PARTIAL or NOT TESTED in the claim ledger rather than
  carried forward as passes.
