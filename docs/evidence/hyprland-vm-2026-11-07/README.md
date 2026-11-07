# Live Hyprland VM evidence

Ubuntu 26.04, Hyprland 0.53.3, Linux 7.0.0-43, QEMU 10.2.1 with CPU emulation and a 2D virtio GPU. The installed omnimcp wheel runs in the guest; no pytest or desktop mocks are involved.

The initial acceptance passed real MCP stdio, desktop snapshot, Foot launch, a 1280x720 PNG capture, keyboard input with independent file readback, and closing the fixture window.

The compositor crashed inside libaquamarine on the subsequent SIGTERM teardown. That is recorded as a remaining environment limitation; it does not invalidate the completed input/file/window observations. A follow-up run is checking the supported compositor exit dispatcher and adding pointer verification.
