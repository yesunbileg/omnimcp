# Verified external-audit fixes — 2026-11-08

Verified external-audit defects were remediated on `wip/audit-fixes-20261107`.
The tested code is `4b277c0`. Earlier independent Terra review identified additional
gaps that were addressed with regressions. The final revised code was implemented
and verified directly; no final independent Terra approval is claimed.

## Changes

- Legacy screenshot/zoom no longer mirror images into structuredContent.
- Compact MCP faults set isError=true with an unchanged JSON payload. A successful
  job lookup still returns lifecycle failures as data.
- RPC timeout/disconnect distinguishes unknown execution outcome from an absent worker.
- Legacy desktop outcomes use typed markers rather than English text guesses.
- Runtime/state/lock paths validate trusted ancestors and use no-follow descriptor
  opens and anchored atomic writes. FIFOs and unsafe truncation are rejected.
- Helper installation is manual guidance only. Optional privileged updates require
  a root-controlled exact-path policy, descriptor-based traversal and per-user
  backups. Root-helper and admin-path tests use isolated fixtures, not real elevation.
- Client auth_retry cannot clear a persisted cancellation block. The local
  `omnimcp worker auth-reset` operator control shares the user's authority and
  does not establish an independent human-consent boundary. Concurrent prompting
  is constrained within one worker process.
- Shutdown cancels before waiting, accounts for whole RPC lifetimes and bounds
  the caller's wait across Store locks and close hooks. Uncooperative worker exit
  is explicitly hard, not graceful. Pending foreground/background process records
  survive independently of job status; no blind signal follows identity loss.
- README is a short Mongolian features/examples page with linked detailed guides.
  Plugin configurations are portable while both compatibility formats remain.
- CI adds build, formatting, subprocess-aware coverage and real Hyprland acceptance.
  The coverage floor is 82%, from the measured audited baseline of 82.65%.

## Verification

- Complete native suite: **1,480 passed, 16 deselected**, 65.98 seconds.
- Subprocess-aware coverage: **84.61%**. Worker and root-helper tests are measured;
  subprocess execution is not misreported as no tests.
- Ruff check, format check and diff whitespace check passed; 133 Python files formatted.
- The final wheel and source distribution were rebuilt during VM staging. All
  **55 installed Python modules** in the fresh runtime image matched the checkout
  byte for byte before that image was used for the disposable guest.
- Measured module coverage: admin adapter **87.93%**, root helper **82.52%**,
  worker **87.76%**, and state/process persistence **87.60%**.
- The first integrated suite had two failures (1,468 passed): an old exact message
  assertion and a PID-reuse fixture that changed only legacy job metadata. The
  compatible message was retained and the fixture now changes the authoritative
  process ledger. A separately reproduced identity-read AccessDenied was also fixed.
- The audited baseline measured with explicit private XDG runtime: 1,364 passed,
  16 deselected; 82.65% coverage, including worker 88.54%. An initial baseline run
  without that private runtime had two environment-path permission failures.

## Actual Hyprland VM

The new wheel was installed into a fresh runtime image and exported to a new VM
disk. Actual MCP stdio, desktop snapshot, Foot launch, cursor readback at (320,240),
screenshot, fresh terminal text/file readback and fixture close all **passed**.

Compositor teardown still **failed with exit 139** in libaquamarine after those
checks completed. The raw runner returned **2**; the CI desktop-only wrapper
recorded `teardown=known_failure` and `release_ready=false`. This is a current
observed failure, not just historical evidence. No clean full-VM lifecycle pass
is claimed. Unexpected crashes, timeouts, missing evidence and failed desktop
effects fail CI; only the exact known version/signature gets an explicit warning.

[Raw VM JSON, screenshot, original serial bytes, coverage and test logs](../evidence/external-audit-2026-11-08/README.md)
are preserved. The 16 excluded live pytest cases were not run. This acceptance
uses file-mode screenshots; the image-duplication fix is separately verified
through the actual pinned MCP client/server protocol with synthetic capture data:
700,000 raw bytes produced one image block, no structuredContent, and a 933,599-byte
response JSON.

## Limits

No real polkit approval, helper installation or privileged host mutation was run.
Root-controlled policy/ownership/race behaviors were exercised in unprivileged
fixtures. No OS sandbox, named-seat isolation, crash-proof launch handshake,
physical-GPU or multi-monitor certification is claimed. Main remains unchanged.

Static type checking, py.typed publication, forced plugin/runtime version equality,
removal of compatibility manifests and rewriting historical evidence were not
accepted as demonstrated runtime defects. Arbitrary user commands remain an
intentional capability, with the user's authority.
