"""Desktop entries, user AppImages and explicit Flatpak installation scopes."""

from __future__ import annotations

import configparser
import hashlib
import os
import re
from pathlib import Path
from typing import Literal

from omnimcp.adapters.files import replace
from omnimcp.core.registry import Fault


def entries(ctx, query: str = "") -> list[dict]:
    """Read available desktop applications from explicit XDG application directories."""
    directories = [
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))),
        *(
            Path(p)
            for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
        ),
    ]
    rows = {}
    for directory in directories:
        for path in sorted((directory / "applications").glob("*.desktop")):
            if path.name in rows:
                continue
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
                if entry.get("Hidden", "false") == "true":
                    continue
                row = {
                    "id": path.name,
                    "name": entry.get("Name", ""),
                    "exec": entry.get("Exec", ""),
                    "path": str(path),
                    "terminal": entry.get("Terminal", "false") == "true",
                }
                if query.lower() in f"{row['id']} {row['name']}".lower():
                    rows[path.name] = row
            except (OSError, KeyError, configparser.Error):
                continue
    return list(rows.values())


def launch(ctx, desktop_id: str) -> dict:
    """Launch an installed desktop entry using background-aware desktop functions."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.desktop", desktop_id):
        raise Fault("invalid_params", "Select an application ID from app.list.")
    return ctx.engine.execute("desktop.launch", {"command": "gtk-launch " + desktop_id}, ctx)


def appimage(ctx, source: str, name: str, sha256: str, expected_revision: str = "missing") -> dict:
    """Install a checksum-verified local AppImage to ~/.local/bin without executing it."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise Fault("invalid_params", "name must be a simple executable name.")
    path = Path(source).expanduser()
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise Fault("verification_failed", "Source checksum does not match.")
    target = Path.home() / ".local/bin" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    result = replace(ctx, str(target), expected_revision, data, mode=0o755)
    result["executable"] = str(target)
    result["verification"] = (
        "Checksum and installation verified; application startup is a separate action."
    )
    return result


def flatpak(
    ctx,
    operation: Literal["install", "remove", "update"],
    ref: str,
    scope: Literal["user", "system"] = "user",
    remote: str = "flathub",
) -> dict:
    """Flatpak transaction and info readback, with explicit installation scope."""
    for value in (ref, remote):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+/-]*", value):
            raise Fault("invalid_params", "Use a Flatpak ref/remote, without option-like values.")
    argv = [
        "flatpak",
        "--" + scope,
        {"install": "install", "remove": "uninstall", "update": "update"}[operation],
        "-y",
    ]
    if operation == "install":
        argv.append(remote)
    result = ctx.run([*argv, ref], admin=scope == "system", timeout=86400)
    if result["status"] != "ok":
        return result
    state = ctx.run(["flatpak", "--" + scope, "info", ref], accepted=(0, 1))
    good = state["exit_code"] == (1 if operation == "remove" else 0)
    return {
        "status": "ok" if good else "verification_failed",
        "verified": good,
        "state": state,
        "transaction": result,
    }


def register(r):
    r.add("app.list", entries, readonly=True, idempotent=True)
    r.add("app.launch", launch, dependencies=("gtk-launch",))
    r.add(
        "package.appimage_install",
        appimage,
        resources=("appimage-install",),
        undo="file.restore for replaced files; a fresh install can be explicitly removed.",
    )
    r.add(
        "package.flatpak_change",
        flatpak,
        dependencies=("flatpak",),
        privilege="GUI for system installation",
        resources=("flatpak-database",),
        verification="Flatpak info readback after transaction.",
    )
