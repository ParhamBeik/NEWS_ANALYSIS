# Performance evidence

Settled route render timings were measured in the authenticated existing browser tab at the normal viewport. Each route was observed three times; the ready condition required final content rather than a loading skeleton.

| Route | Observation 1 | Observation 2 | Observation 3 | Ready condition |
| --- | ---: | ---: | ---: | --- |
| `/` | 757 ms | 734 ms | 643 ms | “stories match” visible and no skeleton |
| `/ops` | 1,255 ms | 1,265 ms | 1,244 ms | “RECENT RUNS” visible and no skeleton |
| `/market` | 885 ms | 705 ms | 803 ms | “PREDICTION OUTCOMES” visible and no skeleton |

Additional observations:

- Feed category-filter navigation settled in 457 ms and returned a URL containing `category=security`.
- Browser console warning/error collection was empty for the inspected normal routes.
- Normal-viewport page-level horizontal overflow was false on feed, review, ops, market, and exports; tables used internal overflow patterns where appropriate.
- The first immediate accessibility snapshot can capture a streaming skeleton on slower dashboard responses; after settling, Operations rendered its complete data. This is a timing observation, not a persistent blank-page defect.
- A protected export download completed as a browser download event without navigating away from the export page.
- No official performance budget was found, so these are observations rather than pass/fail claims against an invented threshold.
