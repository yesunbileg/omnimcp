#!/bin/bash
set -u
export PATH=/opt/omnimcp-venv/bin:/usr/bin:/bin
export OMNIMCP_ARTIFACT_DIR=/mnt/results
/usr/bin/Hyprland --config /home/tester/hyprland.conf > /mnt/results/hyprland.log 2>&1 &
hypr_pid=$!
cleanup() {
    hyprctl dispatch exit >/dev/null 2>&1 || true
    for n in $(seq 1 50); do
        kill -0 "$hypr_pid" 2>/dev/null || break
        sleep .1
    done
    kill "$hypr_pid" 2>/dev/null || true
    wait "$hypr_pid"
    compositor_status=$?
    printf '{"exit_code":%d}\n' "$compositor_status" > /mnt/results/compositor-exit.json
}
trap cleanup EXIT
for n in $(seq 1 120); do
    socket=$(find "$XDG_RUNTIME_DIR/hypr" -name .socket.sock 2>/dev/null | head -1)
    if [ -n "$socket" ]; then
        export HYPRLAND_INSTANCE_SIGNATURE=$(basename "$(dirname "$socket")")
        display=$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -type s -name 'wayland-*' | head -1)
        export WAYLAND_DISPLAY=$(basename "$display")
        if hyprctl -j monitors > /mnt/results/monitors.json 2>/dev/null; then
            echo "HYPRLAND_READY=$HYPRLAND_INSTANCE_SIGNATURE"
            /opt/omnimcp-venv/bin/python /home/tester/desktop_acceptance.py
            exit $?
        fi
    fi
    if ! kill -0 "$hypr_pid" 2>/dev/null; then
        echo 'HYPRLAND_EXITED'
        tail -80 /mnt/results/hyprland.log
        exit 1
    fi
    sleep 1
done
echo 'HYPRLAND_START_TIMEOUT'
tail -80 /mnt/results/hyprland.log
exit 1
