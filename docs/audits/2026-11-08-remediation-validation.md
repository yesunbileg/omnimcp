# Verified external-audit fixes — 2026-11-08

The primary agent completed the remaining implementation after the user's request
to work directly. Earlier independent Terra review identified additional gaps;
those review findings were addressed with new regressions. This report does not
claim that Terra independently approved the final revised code.

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

## Verification so far

- Complete native suite: **1,480 passed, 16 deselected**, 65.98 seconds.
- Subprocess-aware coverage: **84.61%**. Worker and root-helper tests are measured;
  subprocess execution is not misreported as no tests.
- Ruff check, format check and diff whitespace check passed; 133 Python files formatted.
- Wheel and source distribution build passed before the final identity-read fix;
  the VM staging command rebuilds the final wheel before installation.
- The first integrated suite had two failures (1,468 passed): an old exact message
  assertion and a PID-reuse fixture that changed only legacy job metadata. The
  compatible message was retained and the fixture now changes the authoritative
  process ledger. A separately reproduced identity-read AccessDenied was also fixed.
- The audited baseline measured with explicit private XDG runtime: 1,364 passed,
  16 deselected; 82.65% coverage, including worker 88.54%. An initial baseline run
  without that private runtime had two environment-path permission failures.

Live VM validation is pending in this commit. The known Hyprland 0.53.3 /
Aquamarine 0.10 teardown exit 139 remains a separate release gate. CI preserves
raw exit 2 and accepts only the precisely identified known teardown signature as
an explicit warning after actual desktop acceptance and evidence validation.
Unexpected crashes, timeouts, missing evidence and failed desktop effects fail CI.

## Limits

No real polkit approval, helper installation or privileged host mutation was run.
Root-controlled policy/ownership/race behaviors were exercised in unprivileged
fixtures. No OS sandbox, named-seat isolation, crash-proof launch handshake,
physical-GPU or multi-monitor certification is claimed. Main remains unchanged.

Static type checking, py.typed publication, forced plugin/runtime version equality,
removal of compatibility manifests and rewriting historical evidence were not
accepted as demonstrated runtime defects. Arbitrary user commands remain an
intentional capability, with the user's authority.
