# Verification record and release gates

> **Historical record (2026-10-21).** This document describes the installation and tests on that date, not the current feature set. See [the 2026-11-09 feature-removal record](audits/2026-11-09-board-feature-removal.md) for the later removal status.

Validation date: 2026-10-21, Arch Linux, existing Hyprland/Caelestia user session.
The baseline dirty tree was archived outside the repository before editing.

## Automated checks

- Baseline: 1041 passed, 16 live desktop tests deselected.
- Final expanded full suite: 1072 passed, 16 live desktop tests deselected.
- Focused post-version/package/core regression suite: 53 passed.
- Focused Ruff validation covers all new core/adapter/transport modules and new
  tests/scripts. Pre-existing legacy files are not reformatted wholesale.
- Wheel and sdist build with `uv build`; scripts/docs/systemd template are included
  in the sdist, Python adapters/helper and bundled skill in the wheel.

New tests exercise strict schemas and observation boundaries, large-artifact
lossless reconstruction, stale revisions, backup/restore, concurrent writes,
worker interruption, cancellation, workflow references/conditions/waits/deadlines,
GUI cancellation/success/timeout simulation, one-shot retry authorization,
process/window stale references, semantic readback failures, real Unix sockets,
actual MCP stdio conversion, bridge disconnect and controlling PTYs.

```sh
uv run pytest -q
uv run ruff check src/omnimcp/core src/omnimcp/adapters \
  src/omnimcp/compact.py src/omnimcp/core_cli.py \
  src/omnimcp/root_helper.py src/omnimcp/legacy_transport.py \
  tests/test_core.py tests/test_worker.py tests/test_native_adapters.py \
  scripts/benchmark.py scripts/gateway_benchmark.py scripts/live_smoke.py
```

## Live host checks

Executed `uv run python scripts/live_smoke.py --desktop --browser --output docs/live-smoke.json`
against the installed user worker; all recorded checks passed. The script creates its own transient
user service and temporary files, restarts/verifies only that service, and tests
file round-trip preservation on the home/workspace filesystems. Optional desktop
checks capture an 8x8 region without switching focus and launch/close only a
separate hidden Kitty fixture. The JSON record is the evidence for checks actually
run; availability-only results do not establish backend mutation correctness.

Browser navigation, snapshot, form fill, click and independent DOM readback passed
in a separate headless automation profile against a local HTTP fixture. Desktop
launch/close and an 8x8 screenshot preserved the original user focus. File changes
and backup/restore preserved 0640 mode on both ext4 and NTFS3. The NTFS3 check found
and fixed attempts to rewrite already-matching $LXUID/$LXGID/$LXMOD metadata.
No existing user browser/tab was attached. Only the fixture user service restarted.

## Measurements and unfulfilled release gates

`benchmark-local.json` records schema bytes and warmed in-process engine dispatch.
It is not a model token comparison. The separate `benchmark-gateway.json` records
100 warm MCP stdio + socket samples over a private file, subtracting measured
worker backend time: p50 6.396 ms, p95 17.543 ms (target <100 ms passed). The initial
observed schema sizes were 22,263 bytes legacy and 3,949 bytes compact (14 versus
7 tools). Adding capability adapters does not change the compact tool schema.

Still required before switching the default profile:

- Paired actual model/client traces for all 20 tasks, same initial state, counting
  schema/discovery/arguments/results/screenshots/retries; >=50% median token and
  round-trip reductions, with no success-rate regression.
- Real polkit approval/cancellation/timeout interaction. Existing auth tests use an
  isolated fake pkexec; the optional root helper is not silently installed.
- Package mutations, NetworkManager checkpoint rollback, storage mount/format,
  power transitions, Bluetooth pairing, Docker/SSH/Android/VM changes and restic
  end-to-end checks in configured disposable environments/devices.
- No destructive network/boot/disk tests on the daily-use system.

Legacy remains the default. Optional missing dependencies report their exact
availability status; they are not claimed to have passed integration.

## Installed state

- User-local CLI reports `omnimcp 0.2.0`; user systemd worker is enabled/active.
- Installed Python dependencies match the tested uv.lock (constraints exported for
  installation); mcp 1.28.1 and psutil 7.2.2.
- Optional browser backend @playwright/mcp 0.0.83 and Chromium 1247 are installed
  user-locally; private browser.json selects headless automation and its own profile.
- Existing Codex MCP configuration remains legacy; its configured Kanban path is
  retained for the worker. Client reconnection is needed to adopt the updated package.
- No root helper was installed, no real admin prompt opened, no existing service or
  package/network/storage/power configuration was modified by smoke testing.
- Existing pre-task source files were checked against the archived baseline. Only
  the intended integration/version/docs/session files differ, excluding generated
  bytecode; existing Canvas/Kanban implementations remain unchanged.
