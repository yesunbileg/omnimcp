FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && kernel_pkg="$(apt-cache depends linux-image-generic | awk '/Depends: linux-image-[0-9]/{print $2; exit}')" \
    && test -n "$kernel_pkg" \
    && apt-get install -y --no-install-recommends \
    "$kernel_pkg" "linux-modules-${kernel_pkg#linux-image-}" \
    qemu-system-x86 qemu-utils initramfs-tools \
    hyprland mesa-utils libgl1-mesa-dri xwayland foot kitty grim wtype \
    dbus-x11 python3 python3-venv python3-pip busybox-static e2fsprogs \
    udev seatd fonts-dejavu-core curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN if getent passwd 1000 >/dev/null; then \
        old_user="$(getent passwd 1000 | cut -d: -f1)"; \
        usermod -l tester -d /home/tester -m "$old_user"; \
    else useradd -m -u 1000 tester; fi \
    && groupadd -f tester && usermod -g tester -aG video,input tester
COPY runtime-requirements.txt omnimcp-0.2.0-py3-none-any.whl /tmp/
RUN --mount=type=secret,id=proxy_ca,required=true \
    python3 -m venv /opt/omnimcp-venv \
    && /opt/omnimcp-venv/bin/pip --cert /run/secrets/proxy_ca install --require-hashes \
       --index-url https://pypi.org/simple -r /tmp/runtime-requirements.txt \
    && /opt/omnimcp-venv/bin/pip install --no-deps /tmp/omnimcp-0.2.0-py3-none-any.whl
