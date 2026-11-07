"""Optional root-owned file helper. No root Python imports from this checkout."""

import json
import os
import stat
from pathlib import Path

HELPER = Path("/usr/local/libexec/omnimcp-file-helper")
POLICY = Path("/etc/omnimcp/allowed-configs.json")


def availability():
    missing = []
    try:
        root_info = Path("/").lstat()
        if (
            stat.S_ISLNK(root_info.st_mode)
            or root_info.st_uid != 0
            or stat.S_IMODE(root_info.st_mode) & 0o022
        ):
            raise ValueError("root directory is unsafe")
        for managed in (HELPER, POLICY):
            current = Path("/")
            for part in managed.parts[1:]:
                current = current / part
                try:
                    info = current.lstat()
                except FileNotFoundError:
                    missing.append(str(managed))
                    break
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError(f"symlink in managed path {current}")
                if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                    raise ValueError(f"untrusted owner or mode at {current}")
                if current == managed and not stat.S_ISREG(info.st_mode):
                    raise ValueError(f"managed file is not regular: {current}")
        if missing:
            return {
                "status": "missing_dependency",
                "dependencies": sorted(set(missing)),
                "reason": "Install the audited helper and root-controlled allowlist manually.",
            }
        policy = json.loads(POLICY.read_text())
        if not isinstance(policy, list) or any(
            not isinstance(path, str) or not path.startswith("/") or os.path.normpath(path) != path
            for path in policy
        ):
            raise ValueError("allowlist must be a JSON array of canonical absolute paths")
        return {"status": "available"}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "permission_required", "reason": f"Admin paths are unsafe: {exc}."}


def update(ctx, path: str, expected_revision: str, text: str = "", restore: str = "") -> dict:
    """Atomically update an allowlisted root-owned config through the standalone helper."""
    request = {"path": path, "expected_revision": expected_revision}
    request.update({"restore": restore} if restore else {"text": text})
    body = json.dumps(request).encode()
    if len(body) > 1024 * 1024:
        return {"status": "invalid_params", "message": "Admin request exceeds 1 MiB."}
    ref = ctx.store.put(body, "admin-request")
    private = ctx.store.path(ref)
    try:
        result = ctx.run(
            ["/usr/bin/python3", "-I", str(HELPER), str(private)], admin=True, timeout=120
        )
        if result["status"] != "ok":
            return result
        receipt = json.loads(result["text"])
        if receipt.get("verified"):
            receipt["undo"] = {
                "action": "config.admin_update",
                "params": {
                    "path": path,
                    "expected_revision": receipt["revision"],
                    "restore": receipt["backup"],
                },
            }
        return receipt
    finally:
        private.unlink(missing_ok=True)


def install(ctx) -> dict:
    """Provide manual installation instructions without elevating editable package code."""
    del ctx
    return {
        "status": "permission_required",
        "guidance": (
            "A local root operator must review and install the standalone helper at "
            f"{HELPER} and create the root-owned JSON allowlist at {POLICY}. "
            "Do not install code directly from an editable user-writable checkout."
        ),
        "helper": str(HELPER),
        "policy": str(POLICY),
    }


def register(r):
    r.add(
        "admin.install_helper",
        install,
        dependencies=(),
        privilege="manual root operator",
        resources=("admin-helper",),
        verification=(
            "Verify helper, policy and ancestors are root-owned and not group/world writable."
        ),
    )
    r.add(
        "config.admin_update",
        update,
        available=availability,
        dependencies=("pkexec",),
        privilege="GUI admin through root-owned standalone helper",
        resources=lambda p: ("file:" + str(Path(p["path"]).resolve()),),
        verification=(
            "Root helper checks allowlist, revision, backup token, atomic replace and readback."
        ),
        undo="Returned config.admin_update receipt restores a root-held backup.",
    )
