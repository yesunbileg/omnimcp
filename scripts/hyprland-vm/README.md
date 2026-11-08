# Live Hyprland VM acceptance

Run the installed OmniMCP wheel against Hyprland in a CPU-emulated QEMU guest.
The guest has a virtio DRM device and Mesa software rendering. The host needs
Docker, Python, uv, about 6 GB free disk, and 3 GB available RAM; a physical GPU
and KVM are unnecessary for this harness.

Verified versions: Ubuntu 26.04, Linux 7.0.0-43, Hyprland 0.53.3,
Aquamarine 0.10.0, QEMU 10.2.1, Python 3.14, OmniMCP 0.2.0.

## Prepare and run

These commands target the managed cloud checkout at `/workspace/omnimcp`.
The helpers use `/workspace/.omnimcp-runtime/hypr-vm` for disposable artifacts.
`prepare-image.sh` refuses an existing `root.img` or `rootfs.tar`; archive the
previous disposable disk/export before rebuilding. `run-vm.sh` archives the
previous results directory automatically and rejects concurrent runs.

```bash
cd /workspace/omnimcp
export UV_CACHE_DIR=/workspace/.cache/uv
vm_dir=/workspace/.omnimcp-runtime/hypr-vm
mkdir -p "$vm_dir"
cp scripts/hyprland-vm/* "$vm_dir/"
uv export --frozen --no-dev --no-emit-project --format requirements-txt \
  --output-file "$vm_dir/runtime-requirements.txt"
uv build --out-dir "$vm_dir/wheels"
cp "$vm_dir/wheels/omnimcp-0.2.0-py3-none-any.whl" "$vm_dir/"
env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY \
  -u DOCKER_CERT_PATH docker --host=unix:///var/run/docker.sock build \
  --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -t omnimcp-hypr-vm:local "$vm_dir"
bash "$vm_dir/prepare-image.sh"
bash "$vm_dir/run-vm.sh"
```

The package install uses signed Ubuntu repositories and hash-locked Python
dependencies. Preserve the Docker proxy configuration and CA trust. The VM run
container has networking disabled and shares only this harness's artifact
directory. It powers off after acceptance. Live processes are not retained.

## Read both outcomes

`results/desktop-acceptance.json` records real MCP stdio, a desktop snapshot,
Foot window launch, cursor movement with independent compositor readback,
PNG capture, keyboard input with independent file readback, and window close.
The click request is issued, but a separate click effect is not asserted.
`results/desktop-acceptance.png` shows the typed command and its output.

`results/compositor-exit.json` records compositor teardown separately.
The runner exits 0 only when desktop acceptance passes and the compositor exits
cleanly; 1 means missing/failed acceptance and 2 means acceptance passed with a
failed compositor teardown. QEMU launch/timeout errors retain their own status.

**Observed limitation:** this tested compositor/VM combination exits 139 in
libaquamarine during teardown, including through `hyprctl dispatch exit`.
The desktop operations pass, while the complete runner currently returns 2.
Do not suppress that status or describe teardown as successful.

The 16 live pytest cases from the native suite were not executed in this guest.
This manual acceptance does not establish accessibility, polkit, multi-monitor,
or physical GPU behavior. See the committed
[runtime evidence](../../docs/evidence/hyprland-vm-2026-11-07/README.md).

## CI and custom artifact directories

Set `OMNIMCP_VM_DIR` to a fresh absolute directory to use these helpers outside
the managed checkout. `ci-run.sh` exports locked requirements, rebuilds the wheel
and image, boots the actual compositor, and preserves raw results. Existing
images/results must not be overwritten; use a fresh directory for a fresh build.

CI gates the desktop effects and required evidence, including the real text
marker, cursor readback and PNG. The raw runner still returns 2 for the tested
Hyprland 0.53.3/Aquamarine 0.10 teardown exit 139. `ci_result.py` recognizes only
that exact version and diagnostic signature after desktop acceptance succeeds,
records `teardown=known_failure` and `release_ready=false`, and emits a warning.
Timeouts, missing evidence, unknown crash signatures and failed desktop checks
fail CI. A green desktop acceptance check does not close the compositor
lifecycle release gate. Full raw logs and the original exit code are uploaded.
