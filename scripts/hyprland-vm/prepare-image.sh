#!/bin/bash
set -euo pipefail
vm_dir=${OMNIMCP_VM_DIR:-/workspace/.omnimcp-runtime/hypr-vm}
for artifact in root.img rootfs.tar; do
    if [ -e "$vm_dir/$artifact" ] || [ -L "$vm_dir/$artifact" ]; then
        echo "Refusing to overwrite $vm_dir/$artifact; archive the previous disposable VM first." >&2
        exit 1
    fi
done
docker_local() {
    env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY \
        -u DOCKER_CERT_PATH docker --host=unix:///var/run/docker.sock "$@"
}
guest_container=$(docker_local create omnimcp-hypr-vm:local /bin/true)
trap 'docker_local rm "$guest_container" >/dev/null' EXIT
docker_local export --output "$vm_dir/rootfs.tar" "$guest_container"
mkdir -p "$vm_dir/results"
chmod 777 "$vm_dir/results"
docker_local run --rm --network none --mount "type=bind,src=$vm_dir,dst=/output" \
    omnimcp-hypr-vm:local bash -euc '
        mkdir /guestroot
        tar -xpf /output/rootfs.tar -C /guestroot
        cp /output/guest-init.sh /guestroot/root/guest-init.sh
        cp /output/run-desktop.sh /output/hyprland.conf /output/desktop_acceptance.py /guestroot/home/tester/
        chmod +x /guestroot/root/guest-init.sh /guestroot/home/tester/run-desktop.sh
        mkdir -p /guestroot/mnt/results
        cp /boot/vmlinuz-* /output/kernel
        cp /boot/initrd.img-* /output/initrd
        truncate -s 4G /output/root.img
        mkfs.ext4 -F -q -d /guestroot /output/root.img
        echo VM_DISK_PREPARED
    '
