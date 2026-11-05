"""Optional root-owned file helper. No root Python imports from this checkout."""

import json
import stat
from pathlib import Path

HELPER = Path("/usr/local/libexec/agentic-os-mcp-file-helper")


def availability():
    if not HELPER.exists():
        return {
            "status": "missing_dependency",
            "dependencies": [str(HELPER)],
            "reason": "Install the audited root-owned helper separately with GUI authentication.",
        }
    for path in [HELPER, *HELPER.parents]:
        info = path.stat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
            return {
                "status": "permission_required",
                "reason": "Helper and ancestors must be root-owned and not group/world writable.",
            }
    return {"status": "available"}


def update(ctx, path: str, expected_revision: str, text: str = "", restore: str = "") -> dict:
    """Atomically update an existing root-owned config, or restore a returned root backup token."""
    request = {"path": path, "expected_revision": expected_revision}
    request.update({"restore": restore} if restore else {"text": text})
    ref = ctx.store.put(json.dumps(request).encode(), "admin-request")
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
        # Contents may contain application credentials; never leave the request body in artifacts.
        private.unlink(missing_ok=True)


def install(ctx) -> dict:
    """Install the standalone root-owned helper using one graphical authentication request."""
    source = Path(__file__).resolve().parents[1] / "root_helper.py"
    result = ctx.run(
        ["install", "-D", "--owner=root", "--group=root", "--mode=0755", str(source), str(HELPER)],
        admin=True,
        timeout=120,
    )
    if result["status"] != "ok":
        return result
    state = availability()
    return {
        "status": "ok" if state["status"] == "available" else "verification_failed",
        "verification": state,
        "helper": str(HELPER),
    }


def register(r):
    r.add(
        "admin.install_helper",
        install,
        dependencies=("pkexec", "install"),
        privilege="GUI admin",
        resources=("admin-helper",),
        verification=(
            "Verify helper and ancestors are root-owned and not writable by other users."
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
            "Root helper checks revision, verified backup, atomic replace and SHA-256 readback."
        ),
        undo="Returned config.admin_update receipt restores a root-held backup.",
    )
