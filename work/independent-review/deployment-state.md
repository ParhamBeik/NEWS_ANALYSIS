# Git, CI/CD, and deployment state

## Repository

- Local branch: `review/independent-e2e-remediation`, one local review commit above `87fddf5`.
- Remote branch: `origin/main` at the same SHA.
- Current review: committed locally, not pushed.
- Previous-task remediation commits are merged ancestors of current `main`.

## CI/CD

- Previous remediation CI and deploy runs reached terminal `success` on 2026-09-13.
- They were not causally gated: both workflows started on each push, and the second deployment
  finished at 05:25:40Z before CI finished at 05:26:09Z.
- Commit `1d83dd3` changed deployment to wait for successful CI, deploy the tested SHA, and roll
  back on failed verification.
- Current HEAD CI `34971606492` and deploy `34971739622` both reached terminal `success`.

## Live production

- Current host: Iran VPS `45.139.10.12`; the former VPS is out of commission.
- Backend and frontend images run exact SHA
  `87fddf501601f60480bf7e441196ad79cded812d`.
- Application containers were healthy and internal health returned HTTP 200. Server-side edge
  probes returned the expected 200/307 responses, but those do not prove Iranian client access.
- Normal DNS resolved the hostname to the ISP sinkhole `10.10.34.36`; direct queries addressed to
  Cloudflare, Google, and Quad9 were intercepted to the same result. Normal HTTP/HTTPS timed out.
  Direct-IP TLS attempts to Google and Cloudflare DNS-over-HTTPS were reset. From the VPS, the same
  hostname resolved correctly to `45.139.10.12`, isolating the wrong DNS answer to the client ISP
  path. Forcing the correct app mapping returned HTTP 200 and completed a TLS 1.3 SNI handshake,
  but the certificate chains to Caddy Local Authority and is not publicly trusted.
- The live edge's private-CA TLS configuration differs from the repository edge template, which
  expects ACME with a real hostname. This is production configuration drift, not an application
  image defect.
- CSP, frame, content-type, permissions, and referrer headers were present; HSTS was absent. HSTS
  should not be enabled until the public hostname and trusted-certificate path are stable.
- Provider circuit state was `open_budget`; `next_probe_at` was 2026-09-13 10:21:51Z, but the
  weekly periodic task last ran at 00:30Z that day and did not become eligible again for a week.
- Latest readable archive observed: `newsintel-20260918-091029.dump`. After the 2026-09-18 host
  restart, `pg_dump` initially met a refused database connection and the running script deferred
  its next attempt for 86,400 seconds.

Verdict: **internally healthy, publicly blocked**. This review performed read-only inspection. It
did not push, deploy, restart services, change configuration, alter permissions, or write data.
