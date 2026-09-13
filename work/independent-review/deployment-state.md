# Git, CI, deployment, and live state

| State | Evidence | Result |
| --- | --- | --- |
| Local committed branch | `main` at `0569caa54c7b6d25a273e29630b28090a7be184f` | VERIFIED |
| Remote branch | `origin/main` at the same SHA | VERIFIED |
| Earlier release | `c6a2a83` is an ancestor; CI `34474700914` and Deploy `34474700980` were terminal successes | VERIFIED |
| Current committed CI | CI `34712380694` was terminal success for `0569caa` | VERIFIED |
| Current committed deployment | Deploy `34712380653` terminal success; VPS image tags both equal `0569caa` | VERIFIED |
| Local remediation | Uncommitted frontend changes and tests | LOCAL ONLY |
| Pushed remediation | No commit exists for it | NO |
| CI for remediation | No remote SHA exists | NO |
| Deployed remediation | Live browser still reproduces the pre-fix behavior | NO |
| Direct deployed revision/service/log/backup inspection | Read-only VPS inspection: healthy services, internal health 200, zero recent error-pattern lines, full current-archive readback | VERIFIED |
| Released remediation | `13044694482f1a8e9726b8dc9aed502361e09e54`; CI `34740032943`, Deploy `34740032951` | VERIFIED |
| Released sign-out correction | `f9001acfb6b2b34eb831b98bcd01db80dce1bc94`; CI `34740197939`, Deploy `34740197935` | VERIFIED |
| Current VPS parity | Backend and frontend images pinned to `f9001ac`; backend/frontend/db/redis healthy; internal health 200 | VERIFIED |
