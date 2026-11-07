# Hardening continuation: 2026-11-07

This batch completes the remaining owner-settings compatibility and worker
cancellation work from the supplied A19/A20/A21 review against the renamed
`omnimcp` repository. It does not replay the earlier rename or scratch patches.

## Changes

- A FIFO configured as the launch allowlist is refused without blocking.
- Real MCP validation tests receive their own runtime directories; validation
  assertions and real stdio handshakes remain enabled.
- Previous owner environment settings are translated before configuration is
  read. Explicit new settings win; escaped names-only warnings use stderr.
  See [migration steps](MIGRATION.md).
- Normal command cancellation and crash recovery share verified process-group
  cleanup. TERM-resistant descendants are checked individually before KILL;
  concurrent cleanup requests share the result for a recorded identity.
- `omnimcp worker stop-all` cancels queued/running work while retaining the
  daemon, independently terminates recorded groups even if a handler is blocked,
  and reports still-busy threads honestly, including on repeated calls.
- Late progress cannot reopen cancelled jobs. Late subprocess registration
  notices cancellation. Retained process identities on cancelled jobs are
  considered by recovery.
- Legacy stop refuses untrusted beacons and mismatched/missing process birth
  times. Live older beacons without birth times require restarting their server
  through its owning client/service.

## Verification actually executed

| Check | Result |
| --- | --- |
| Full pytest suite, two runs (last run after the repeat-count fix) | 1,364 passed; 16 deselected each run |
| Ruff over the entire checkout | Passed |
| Wheel and source distribution build | Passed |
| Built wheel installed into a fresh temporary venv with hashed, locked runtime dependencies | Passed; CLI version and readonly compatibility verified from site-packages |
| Real MCP stdio, client disconnect/job survival, file write/restore with independent readback, controlling PTY, worker crash/restart | Passed |
| Real owner CLI concurrent with ordinary cancellation | Passed; stubborn process gone, job cancelled, exact termination counts, repeat empty response, daemon still usable |
| MCP control boundary | Seven compact tools; owner stop control absent; act/workflow reject it |
| Blocked handler and queued cancellation | Bounded stop response; queued job never executes; busy thread counts retained on repeat |
| PyPI advisory audit of installed dependencies | 36 audited, zero known advisories; editable local project skipped |

Regression evidence includes a FIFO open timing out before the fix and a
cancelled command leaving a live TERM-resistant descendant before shared cleanup.
Real subprocesses use isolated state/sockets, explicit readiness markers and
recorded process identities. Tests stop only their own fixtures. The initial
offline wheel-install attempt lacked resolver cache metadata; installation was
completed from the lockfile's PyPI index with hash verification enabled.

Machine-local command logs and dependency-audit JSON are retained under
`/workspace/.omnimcp-runtime/reports/`; no credentials are included in this report.

## Remaining work and limits

- Sixteen live Hyprland/background pytest cases were deselected in the native
  suite. A separate CPU-emulated VM ran actual Hyprland desktop acceptance:
  window launch/close, cursor movement, screenshot and keyboard/file readback
  passed. The compositor teardown exits 139; see
  [the separate live evidence](evidence/hyprland-vm-2026-11-07/README.md).
  Those 16 pytest cases, polkit and device mutation checks remain unrun.
- The OS can deny signals, particularly after elevation. Such identities remain
  tracked for recovery on worker restart; another stop-all does not retry a
  denied termination. Inspect job state and processes before further action.
- An uncooperative Python handler cannot be killed as a thread. Stop-all returns
  its busy count; it does not undo already completed changes or guarantee graceful
  worker shutdown while such a handler remains blocked.
- A local shell can invoke the owner CLI; keeping control out of MCP discovery is
  an interface restriction, not a sandbox.
- A17 output/artifact/queue limits, A18 broader error-text and test-safety work,
  and the missing earlier A12b/A14 audit reports remain follow-up work.
