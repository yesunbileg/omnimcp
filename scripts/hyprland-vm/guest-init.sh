#!/bin/bash
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LANG=C.UTF-8
mountpoint -q /proc || mount -t proc proc /proc
mountpoint -q /sys || mount -t sysfs sysfs /sys
mountpoint -q /dev || mount -t devtmpfs devtmpfs /dev
mkdir -p /dev/pts /dev/shm /run /tmp /mnt/results
mountpoint -q /dev/pts || mount -t devpts devpts /dev/pts
mountpoint -q /dev/shm || mount -t tmpfs -o mode=1777,size=256m tmpfs /dev/shm || {
    echo 'GUEST_SETUP_FAILED: shared memory could not be mounted' >&2
    /bin/busybox poweroff -f
    exit 1
}
ln -sfnT /proc/self/fd /dev/fd
ln -sfnT /proc/self/fd/0 /dev/stdin
ln -sfnT /proc/self/fd/1 /dev/stdout
ln -sfnT /proc/self/fd/2 /dev/stderr
mountpoint -q /run || mount -t tmpfs tmpfs /run
chmod 1777 /tmp
modprobe virtio_gpu
modprobe virtio_input
modprobe 9pnet_virtio
mount -t 9p -o trans=virtio,version=9p2000.L hostshare /mnt/results || {
    echo 'GUEST_SETUP_FAILED: results share could not be mounted' >&2
    /bin/busybox poweroff -f
    exit 1
}
exec > >(tee /mnt/results/guest-init.log) 2>&1
echo 'GUEST_BOOTED'
uname -a
ls -l /dev/dri
/usr/lib/systemd/systemd-udevd --daemon
udevadm trigger
udevadm settle --timeout=10
mkdir -p /run/dbus /run/user/1000
dbus-uuidgen --ensure=/etc/machine-id
dbus-daemon --system --fork
chmod 700 /run/user/1000
chown tester:tester /run/user/1000
chown -R tester:tester /dev/dri /home/tester
chmod 777 /mnt/results
SEATD_VTBOUND=0 seatd -g video > /mnt/results/seatd.log 2>&1 &
runuser -u tester -- env XDG_RUNTIME_DIR=/run/user/1000 LIBSEAT_BACKEND=seatd \
  LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe AQ_DRM_DEVICES=/dev/dri/card0 \
  HYPRLAND_NO_SD_NOTIFY=1 dbus-run-session -- /bin/bash /home/tester/run-desktop.sh
result=$?
echo "GUEST_RESULT=$result"
sync
mount -o remount,ro / || true
/bin/busybox poweroff -f
