# Performance and responsiveness observations

## Independent evidence

- The current production Market route was checked at a 390px viewport. Root and body scroll
  widths were 375px against a 390px viewport, so the page had no page-level horizontal
  overflow. This does not prove every responsive surface.
- The final release's CI rebuilt both frontend images and ran the production build before each
  deploy. It is build evidence, not a latency measurement.
- Direct VPS inspection after deployment found healthy frontend and backend containers. It
  does not measure browser render latency or endpoint tail latency.

## Classification of the earlier timing claims

The earlier three-sample timings for Feed, Operations, and Market are retained in
`work/e2e-audit/performance.md` as historical observations only. No published performance
budget, percentile SLO, or comparable baseline exists in the repository. They are therefore
not independently VERIFIED performance passes, and no throughput or load test was run against
production.

## Scope and limitations

The remediation changed error handling, authorization boundaries, and one metric calculation;
it did not add a query fan-out, polling loop, or new background workload. Browser verification
covered the changed routes and auth workflows. Broader dashboard latency and all-breakpoint
responsiveness remain observational rather than performance-certified.
