"""Caelestia shell operations using its published IPC commands, without shell restarts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from omnimcp.core.registry import Fault


def notifications(ctx, offset: int = 0, limit: int = 20) -> dict:
    """Read saved Caelestia notifications without clearing/restarting the shell."""
    import os

    path = (
        Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        / "caelestia/notifs.json"
    )
    if not path.exists():
        return {"status": "unsupported", "reason": "Caelestia notification state file is absent."}
    if offset < 0 or not 1 <= limit <= 100:
        raise Fault("invalid_params", "offset>=0 and limit=1..100.")
    value = json.loads(path.read_text())
    if isinstance(value, list):
        return {
            "status": "ok",
            "items": value[offset : offset + limit],
            "total": len(value),
            "next": offset + limit if offset + limit < len(value) else None,
        }
    return {"status": "ok", "state": value}


def dnd(ctx, enabled: bool) -> dict:
    """Set Do Not Disturb and independently read its state."""
    result = ctx.run(["caelestia", "shell", "notifs", "enableDnd" if enabled else "disableDnd"])
    if result["status"] != "ok":
        return result
    check = ctx.run(["caelestia", "shell", "notifs", "isDndEnabled"])
    verified = check["status"] == "ok" and check["text"].strip().lower() == str(enabled).lower()
    return {
        "status": "ok" if verified else "verification_failed",
        "verified": verified,
        "state": check,
    }


def theme(ctx, name: str, mode: Literal["dark", "light"] = "dark") -> dict:
    """Apply a named Caelestia scheme and read it back."""
    if not name or name.startswith("-"):
        raise Fault("invalid_params", "Select a scheme name from desktop.themes.")
    before = ctx.run(["caelestia", "scheme", "get", "-n"])
    result = ctx.run(["caelestia", "scheme", "set", "--name", name, "--mode", mode], timeout=120)
    if result["status"] != "ok":
        return result
    after = ctx.run(["caelestia", "scheme", "get", "-n"])
    good = after["status"] == "ok" and after["text"].strip() == name
    return {
        "status": "ok" if good else "verification_failed",
        "verified": good,
        "before": before,
        "after": after,
    }


def brightness(ctx, percent: int) -> dict:
    """Set display brightness through Caelestia IPC and return readback."""
    if not 1 <= percent <= 100:
        raise Fault("invalid_params", "percent must be 1..100.")
    result = ctx.run(["caelestia", "shell", "brightness", "set", str(percent / 100)])
    if result["status"] != "ok":
        return result
    check = ctx.run(["caelestia", "shell", "brightness", "get"])
    return {"status": "ok" if check["status"] == "ok" else "verification_failed", "state": check}


def power(ctx, operation: Literal["suspend", "hibernate", "poweroff", "reboot"]) -> dict:
    """Explicit power operation via GUI authentication. Resume/boot verification is external."""
    return ctx.run(["systemctl", operation], admin=True, timeout=120)


def register(r):
    r.add("desktop.notifications", notifications, readonly=True, idempotent=True)
    r.add("desktop.dnd", dnd, dependencies=("caelestia",), resources=("caelestia",))
    r.add("desktop.theme", theme, dependencies=("caelestia",), resources=("caelestia",))
    r.add("display.brightness", brightness, dependencies=("caelestia",), resources=("caelestia",))
    r.add(
        "power.change",
        power,
        dependencies=("systemctl", "pkexec"),
        privilege="GUI admin",
        resources=("power",),
        verification="Dispatch only; resume or boot requires external verification.",
    )
    for name, argv in {
        "desktop.themes": ["caelestia", "scheme", "list"],
        "desktop.theme_status": ["caelestia", "scheme", "get"],
        "display.brightness_status": ["caelestia", "shell", "brightness", "get"],
    }.items():

        def read(ctx, command=argv):
            return ctx.run(command)

        r.add(
            name,
            read,
            params={},
            readonly=True,
            idempotent=True,
            dependencies=("caelestia",),
            description="Read Caelestia state through its CLI.",
        )
