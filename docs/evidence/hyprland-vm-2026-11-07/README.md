# Live Hyprland VM evidence

Ubuntu 26.04, Hyprland 0.53.3, Linux 7.0.0-43, QEMU 10.2.1 with CPU emulation and a 2D virtio GPU. The installed omnimcp wheel runs in the guest; no pytest or desktop mocks are involved.

The initial acceptance passed real MCP stdio, desktop snapshot, Foot launch, a 1280x720 PNG capture, keyboard input with independent file readback, and closing the fixture window.

The compositor crashed inside libaquamarine on the subsequent SIGTERM teardown.

The follow-up acceptance also passed real pointer movement (independent cursor
readback at 320,240), keyboard input and file readback, a screenshot after the
typed command, and fixture closure. The click request was issued; a separate
click effect was not asserted. The running compositor's version was queried
inside the guest and is included in `desktop-acceptance.json`.

Teardown through `hyprctl dispatch exit` also produced exit 139, recorded in
`compositor-exit.json`. This is a diagnosed limitation of the tested
compositor/VM combination; desktop acceptance passed and teardown failed.
The runner reports those separately and returns 2 for that combination.

`desktop.png` is the actual final capture. The `initial-*` files preserve the
earlier completed desktop run. The manual runs use the installed wheel and
real OS processes; the 16 live pytest tests remain unrun. Reproduction commands
are in [the VM helper README](../../../scripts/hyprland-vm/README.md).
