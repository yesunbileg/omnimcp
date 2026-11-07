# External audit remediation evidence

Code: `4b277c0` on `wip/audit-fixes-20261107`.

- `full-final2.log`: 1,480 tests passed; 16 live tests deselected; coverage 84.61%.
- `coverage-summary.json`: measured per-module coverage including subprocesses.
- `full-final.log`: the earlier 2-failure integrated run, retained explicitly.
- `parent-shutdown-red.log` and `identity-denial-red.log`: failures before the
  final direct shutdown and identity-read fixes.
- `desktop-acceptance.json` and PNG: actual fresh-VM MCP desktop actions and a
  freshly generated text marker independently read from disk.
- `vm-image-module-hashes.json`: all 55 installed source modules in the image used
  to create that VM matched the checkout; this is an image check, not a second
  independent in-guest hash probe.
- `compositor-exit.json`, raw runner exit and serial logs: actual teardown **139**,
  runner **2**. `ci-result.json` explicitly leaves `release_ready=false`.
- `serial.raw.log.gz`: original serial bytes. The readable `serial.log` normalizes
  line endings and trailing whitespace only. Red-test logs with whitespace
  normalization also retain their original bytes in adjacent `.raw.gz` files.
- `image-protocol.json` and probe text: actual MCP client/server with synthetic
  capture data; one 700,000-byte image, no structuredContent, 933,599-byte response.
- `metadata.json`: source, build hashes, host and VM validation scope.

The VM is CPU-emulated QEMU with virtio DRM and llvmpipe. Runtime networking is
disabled. The standard probe issues a click but does not independently verify an
application click effect. No real host root mutation, polkit interaction,
named-seat, physical-GPU or multi-monitor validation is asserted.

The workflow is [scripts/hyprland-vm](../../../scripts/hyprland-vm/README.md).
