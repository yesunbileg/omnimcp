# Audit fix validation — 2026-11-07

The four accepted defects in [the independent audit](2026-11-07-review.md)
have scoped fixes on `wip/audit-fixes-20261107`. Main is unchanged at `4b67a7c`.

| Finding | Change | Commit |
| --- | --- | --- |
| F1 keyboard receipt | Snapshot focus before dispatch, after dispatch and after key delivery, including special workspaces. | `3a4e0e4` |
| F2 cancellation exit | Treat `cancellation_requested` as CLI success; retain asynchronous JSON and verify later cancellation. | `5f08b7b` |
| F3 launch attribution | Check resolved class and requested workspace before claiming a new window; leave ambiguous windows untouched. | `bc73e91` |
| F4 pointer rounding | Normalize default-seat coordinates before pointer and foreground click_ui guards; use them for delivery. | `49cf9f7` |

F4 preserves named-seat positioning rather than disabling it. It adds no claim
that named-seat relative-origin assumptions, wire quantization, seat isolation,
or uncached named-seat dry-run readiness are verified. Explicitly requested
seats cannot silently fall back to global default-seat pointer delivery.
Dry runs and refused default-seat calls create no virtual pointer.

## Code verification

- Final full suite: **1,400 passed, 16 deselected**, 55.61 seconds. The configured
  selection excludes tests marked `e2e` or `background`; VM checks are separate.
- Ruff passed; wheel and source distribution built.
- Independent Terra high review approved F1/F2/F3 after source review and 220
  passing keyboard/launch/background tests. Its six worker cases were blocked
  by sandbox Unix-socket `EPERM`; the parent's successful full suite ran those
  actual worker/socket/CLI tests with the required permissions.
- Independent Terra high review additionally ran all six real worker tests
  successfully with local socket permissions, including F2 cancellation.
- Independent Terra high review approved scoped F4 with 180 passing pointer,
  input, background and dry-run tests. Public production-guard regressions
  exercise x=639.6→640 and x=-0.4→0 across adjacent allowed/disallowed windows.
- An intermediate full run failed `test_dryrun.py::test_click_ui` (1 failed,
  1,398 passed): float formatting changed `(40, 50)` to `(40.0, 50.0)`.
  Returning rounded integers fixed that regression before the final run.
- An earlier external report recorded a `test_command_cancellation.py` failure
  followed by a passing complete suite. That history is retained; it was not
  reproduced in this final full-suite run.

## Real runtime evidence

The updated wheel was **reinstalled inside the actual QEMU guest** before the
run. All 53 installed Python modules matched the checkout hashes. The guest
ran Hyprland 0.53.3/Aquamarine 0.10 with virtio DRM and Mesa llvmpipe, Python
3.14, and networking disabled.

- Standard real MCP stdio acceptance passed: desktop snapshot, ordinary Foot
  launch, cursor readback at (320,240), PNG screenshot, a freshly generated text
  marker typed into Foot and independently read from disk, and fixture close.
- **F1 passed:** special:notes over normal workspace 2 changed to the requested
  workspace-1 window in foreground mode. The reply records the original special
  workspace and both subsequent focus snapshots. Background mode preserved the
  special workspace, active window and underlying normal workspace exactly.
- **F3 passed:** the delayed intended launch wrote an exec-start marker before
  the probe opened a real same-class human Foot window. The human window stayed
  on workspace 1; launch returned the intended window on workspace 2. This
  establishes that controlled event ordering, not universal launch provenance.
- **F4 passed:** real adjacent floating windows covered [0,640) and [640,1280).
  A confined click at x=639.6 was rejected as (640,100) over the blocked class.
  Independent cursor readback stayed (100,100). No blocked-window application
  click receipt is claimed; the asserted result is refusal with no movement.
- **Teardown failed:** compositor exit **139**, with a libaquamarine segfault in
  the serial log after acceptance completed. The existing result summarizer
  exits **2**. QEMU poweroff success does not override this outcome.

Independent Terra high review approved the final harness and runtime evidence
with these same limits.

The first extended run stopped at a redundant workspace selection in the
harness (the compositor tried a nonexistent previous workspace); baseline
acceptance had passed. The corrected second run passed; the final run added
an actual exec-start marker to establish launch-race ordering and captured
before/after special-workspace screenshots. Earlier raw results are retained.

[Raw JSON, screenshots, installation log, hashes and exact harness inputs](../evidence/audit-fixes-vm-2026-11-07/README.md)
are committed with this report. The 16 excluded live pytest cases were not run.
Named-seat positioning/isolation, accessibility, physical GPU and multi-monitor
behavior remain outside this validation. Main remains unchanged; these results
do not claim a clean overall compositor lifecycle.
