# Open decisions

Objective corrections were made locally without choosing a new ingress architecture or
publishing. No account, production record, edge configuration, or customer data was changed.

1. **Public access path.** Current behavior: the new VPS is internally healthy, but this Iranian
   client path receives a DNS sinkhole answer; forcing the VPS IP reaches an untrusted private-CA
   certificate. Direct TLS to public DNS-over-HTTPS resolvers is reset. The app's own SNI handshake
   succeeded when its IP was forced on this path, so an across-the-board app SNI block is not
   established. Which access model is intended?
   - **Owned public hostname + ACME certificate (recommended for a public product):** supply the
     owned hostname and authoritative DNS control. Fix the edge certificate and test ordinary
     resolution, TLS, and browser behavior from affected Iranian ISPs; if SNI itself is filtered
     for that hostname, a further reachable ingress/front-door decision is needed. Public users
     get standard HTTPS when the ISP path permits it; operations own DNS and certificate renewal.
   - **Private VPN-only access:** keep the product off public ingress and use a managed tunnel with
     trusted internal DNS/certificates. Fewer public exposure concerns, but every user needs VPN.
   - **Iran-reachable front door/alternate domain:** select a provider/domain after testing its
     actual DNS and TLS path from affected networks. This may restore public use under filtering,
     but adds provider cost and an additional trust/operational boundary.

2. **Publication of reviewed corrections.** Current behavior: fixes and tests are committed only
   on a local review branch; production still has the weekly probe and slow backup retry, although
   the provider circuit closed on its next weekly tick. The release workflow auto-deploys after
   successful CI, so a push is a deployment decision.
   - **Authorize release (recommended once a maintenance window is acceptable):** publish the
     reviewed commit, wait for terminal CI/deploy, and verify probe schedule, backup behavior,
     deployed SHA, and health. This corrects backend recovery even if public ingress remains
     blocked; a restart/rollout is user-visible operational risk.
   - **Hold locally:** no production change or rollout risk; the two recovery defects remain live
     until authority is granted. Browser verification remains independently blocked by tooling
     and ingress.

Neither decision has been supplied by the user. No publication or edge mutation is authorized by
the audit objective alone.
