# Real audit-fix VM evidence

Installed code: `49cf9f7` on `wip/audit-fixes-20261107`; source hash manifest and
wheel hash are recorded here. The disposable guest force-reinstalls the wheel
offline before starting Hyprland, then checks all 53 installed Python modules.
The real worker/socket/CLI cancellation test runs on the host in the full suite;
the compositor checks run in the guest. These are different runtime checks.

The final run uses a Foot wrapper that writes an exec-start marker, waits three
seconds, then execs the intended Foot process. The probe waits for that marker
before opening a same-class human fixture on workspace 1. Both clients are real
Wayland windows; only the test-owned launch timing is controlled.

Raw JSON preserves workspace/client/cursor state and MCP replies.
`serial.raw.log.gz` preserves the original serial bytes; `serial.log` has
normalized line endings and trailing whitespace for readable diffs. PNGs are guest
captures, not generated images. The standard desktop probe also types a fresh
random marker into a real terminal and independently reads the resulting file.
Its issued click has no separately asserted application click effect.

The compositor shutdown result is separate. Exit 139 is an actual observed
libaquamarine teardown crash, not a clean pass and not merely historical.
No named-seat, accessibility, physical-GPU, multi-monitor or universal app
attribution guarantee is established by this run.

`earlier-attempts/attempt1.json` records the harness's redundant workspace-switch
failure after standard desktop acceptance passed. `attempt2.json` passed the
extended checks, but used a timing delay without an exec-start marker. The final
harness strengthens that ordering proof. The source-formatting dry-run failure
and prior reported cancellation-test failure are recorded in the
[validation report](../../audits/2026-11-07-fix-validation.md).

Exact harness inputs are saved under `harness/` as text. Copy them to the same
names without `.txt` in a disposable VM work directory to inspect/reuse them;
`run-vm.sh` uses the managed `/workspace/.omnimcp-runtime/four-fixes-vm` path.
The baseline image preparation and environment requirements remain in
[the VM helper documentation](../../../scripts/hyprland-vm/README.md).
The raw debugfs injection helper must only be used on a stopped disposable image;
it runs e2fsck and compares injected script readback before boot.
