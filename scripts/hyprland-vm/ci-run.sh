#!/bin/bash
# Rebuild the wheel into a disposable real compositor VM and retain both outcomes.
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
: "${OMNIMCP_VM_DIR:?Set OMNIMCP_VM_DIR to a fresh disposable artifact directory}"
mkdir -p "$OMNIMCP_VM_DIR"
for source_file in "$repo_dir"/scripts/hyprland-vm/*; do
    if [ -f "$source_file" ]; then cp "$source_file" "$OMNIMCP_VM_DIR/"; fi
done
uv export --project "$repo_dir" --frozen --no-dev --no-emit-project \
    --format requirements-txt --output-file "$OMNIMCP_VM_DIR/runtime-requirements.txt"
uv build --project "$repo_dir" --out-dir "$OMNIMCP_VM_DIR/wheels"
cp "$OMNIMCP_VM_DIR/wheels/omnimcp_linux-0.2.0-py3-none-any.whl" "$OMNIMCP_VM_DIR/"
git -C "$repo_dir" rev-parse HEAD > "$OMNIMCP_VM_DIR/source-commit.txt"
env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY \
    -u DOCKER_CERT_PATH docker --host=unix:///var/run/docker.sock build \
    --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
    -t omnimcp-hypr-vm:local "$OMNIMCP_VM_DIR"
bash "$OMNIMCP_VM_DIR/prepare-image.sh"
set +e
bash "$OMNIMCP_VM_DIR/run-vm.sh" > "$OMNIMCP_VM_DIR/serial.log" 2>&1
raw_exit=$?
set -e
printf '%s\n' "$raw_exit" > "$OMNIMCP_VM_DIR/raw-runner-exit.txt"
cp "$OMNIMCP_VM_DIR/serial.log" "$OMNIMCP_VM_DIR/results/serial.log"
python3 "$OMNIMCP_VM_DIR/ci_result.py" "$OMNIMCP_VM_DIR/results" "$raw_exit"
