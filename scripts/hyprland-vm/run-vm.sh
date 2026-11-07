#!/bin/bash
set -euo pipefail
vm_dir=${OMNIMCP_VM_DIR:-/workspace/.omnimcp-runtime/hypr-vm}
exec 9>"$vm_dir/run.lock"
flock -n 9 || { echo 'A VM test run already owns this directory.' >&2; exit 1; }
if [ -d "$vm_dir/results" ]; then
    mv "$vm_dir/results" "$vm_dir/results-$(date -u +%Y%m%dT%H%M%SZ)-$$"
fi
mkdir "$vm_dir/results"
chmod 777 "$vm_dir/results"
env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY \
    -u DOCKER_CERT_PATH docker --host=unix:///var/run/docker.sock run --rm \
    --network none --mount "type=bind,src=$vm_dir,dst=/output" \
    omnimcp-hypr-vm:local timeout --signal=TERM --kill-after=15 420 \
    qemu-system-x86_64 -accel tcg,thread=multi -cpu max -m 3072 -smp 2 \
    -kernel /output/kernel -initrd /output/initrd \
    -append 'root=/dev/vda rw console=ttyS0 init=/root/guest-init.sh panic=10' \
    -drive file=/output/root.img,format=raw,if=virtio \
    -vga none -device virtio-vga -device virtio-keyboard-pci -device virtio-mouse-pci \
    -virtfs local,path=/output/results,mount_tag=hostshare,security_model=none,id=hostshare \
    -display none -serial stdio -monitor none -no-reboot
python3 "$vm_dir/summarize.py" "$vm_dir/results"
