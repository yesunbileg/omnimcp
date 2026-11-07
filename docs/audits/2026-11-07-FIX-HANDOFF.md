# Four confirmed audit fixes — unfinished handoff

Base: `4b67a7c0eb11efc3cb60165e38d33039336e5d5e`.
See [independent review](2026-11-07-review.md) and the saved reproduction scripts
in `2026-11-07-repros/`. Four Luna high auditors supplied candidates; a Terra high
reviewer independently adjudicated these four. Other candidates were not proven.

## Current work, not completion

- `src/omnimcp/core_cli.py`: adds `cancellation_requested` to accepted CLI statuses.
- `tests/test_worker.py`: adds a real-worker cancellation/exit-status regression.
  It failed before the fix, as expected: accepted cancellation printed JSON but
  exited 1. The post-fix run was NOT executed: automatic approval review failed
  because the account usage limit was reached. No green claim is made.
- `tests/test_keyboard_target.py`: adds a foreground receipt regression. The
  production keyboard implementation remains unchanged. Verify this new test
  fails for the intended reason rather than fixture limitations.
- `tests/test_launch.py`: starts converting two tests that expected unsafe
  off-workspace browser-window claiming into safe rejection tests. The production
  launch implementation remains unchanged. These tests are unfinished/red.
- Pointer normalization has NOT been implemented and has no new committed
  regression test yet. Source reproduction is saved with the review.

Do not merge this WIP into main as a finished fix. User requests real runtime
validation and regular pushes, with Luna high implementers and Terra high review.

## Required fixes

1. **F4, pointer confinement (P2).** Server guards float coordinates, then the
   default-seat movement rounds them. At x=639.6 inside a permitted [0,640)
   window, it can dispatch x=640 into a neighboring out-of-scope window. Normalize
   before guarding and ensure actual delivery uses the same coordinates. Cover
   pointer click, drag endpoints and click_ui; preserve named-seat subpixel
   semantics. Relevant: `input.py:244`, `server.py:798`, `trust.py:284`.

2. **F3, launch attribution (P2).** `_launched_window` accepts a fuzzy app-class
   match on the human's workspace; launch then marks it owned and moves it to
   the requested workspace. Close this demonstrated path. A conservative fix
   must leave ambiguous off-workspace single-instance windows untouched and
   report ambiguity rather than silently claiming them. Preserve ordinary
   requested-workspace launches. Explicitly document that workspace/class
   matching alone cannot provide a universal provenance guarantee. Relevant:
   `server.py:1649–1656`, `server.py:1776–1789`. Existing single-instance auto-move
   tests need deliberate compatibility updates; do not simply weaken assertions.

3. **F1, foreground keyboard receipt (P3).** Foreground keyboard focuses the
   requested window before the helper snapshots the seat, then falsely says
   "the human's focus untouched". Measure the complete action or explicitly
   describe the foreground takeover. Preserve genuine background=true receipts,
   password/auth guards, dry-run, key delivery and `then` behavior. Relevant:
   `server.py:908–918`, `server.py:1179–1193`.

4. **F2, CLI cancellation result (P3).** Finish/verify the partial change above.
   An accepted asynchronous cancellation request should exit 0 while retaining
   `cancellation_requested` in JSON; this must not claim the job already stopped.
   Relevant: `core_cli.py:125`, worker/engine cancellation handling.

## Validation to complete

Use `XDG_RUNTIME_DIR` in a private writable directory and a writable
`UV_CACHE_DIR`. Do not use actual user desktop data or ambient workers.

- Capture red/green evidence for every fix. Reproduction scripts for F3/F4 use
  simulated IPC; identify that limitation in reports.
- Run real worker/CLI cancellation and verify final job cancellation.
- Run relevant pointer, input, safety, launch, background and keyboard suites.
- Run the full pytest suite, `ruff check .`, and `uv build` after integration.
- Run updated code in the actual Hyprland VM using the existing
  `scripts/hyprland-vm/README.md` workflow. Rebuild/reinstall the wheel: the old
  VM contains old application code. Verify workspace/special-workspace receipts
  and actual cursor positions. Preserve raw output and screenshots.
- The tested Hyprland0.53.3/Aquamarine0.10 VM already has a known teardown
  exit139. Desktop outcomes and compositor teardown must remain separate;
  do not suppress it or claim a clean overall runner pass.
- Get independent Terra high review, address verified issues, and push tested
  commits. A prior Git read also failed with a username prompt; use the provided
  HTTPS proxy authentication and diagnose access, never request secret values
  in chat or invent tokens.

Audit validation before implementation: desktop focused348, files55, core15
tests passed. These counts predate fixes and do not validate this WIP.
