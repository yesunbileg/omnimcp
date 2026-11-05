"""Small explicit wrappers around Linux tools. No shell interpolation or hidden installation."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Literal

from agentic_os_mcp.core.execution import require_ok
from agentic_os_mcp.core.registry import Fault


def identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+@:/=-]*", value):
        raise Fault("invalid_params", "Invalid identifier or option-like value.")
    return value


def packages(ctx, query: str = "", installed: bool = True) -> dict:
    """Search pacman packages or list installed versions."""
    return ctx.run(
        [
            "pacman",
            "-Qs" if installed and query else "-Q" if installed else "-Ss",
            *(["--", query] if query else []),
        ],
        accepted=(0, 1),
    )


def package_change(
    ctx, operation: Literal["install", "remove", "upgrade"], names: list[str] | None = None
) -> dict:
    """Pacman transaction via graphical authentication. Upgrade always uses -Syu."""
    names = names or []
    if operation != "upgrade" and not names:
        raise Fault("invalid_params", "Package names are required.")
    for name in names:
        identifier(name)
        if "/" in name:
            raise Fault("invalid_params", "Use repository package names, not local paths.")
    before = ctx.run(["pacman", "-Q", *names], accepted=(0, 1))
    flags = {"install": ["-S", "--needed"], "remove": ["-R"], "upgrade": ["-Syu"]}[operation]
    result = ctx.run(["pacman", *flags, "--noconfirm", "--", *names], admin=True, timeout=86400)
    if result["status"] != "ok":
        return result
    after = ctx.run(["pacman", "-Q", *names], accepted=(0, 1))
    verified = after["exit_code"] == (1 if operation == "remove" else 0)
    # Check each removal, since pacman returns 1 for a mixed present/absent query too.
    if operation == "remove":
        verified = all(
            ctx.run(["pacman", "-Q", name], accepted=(0, 1))["exit_code"] == 1 for name in names
        )
    return {
        "status": "ok" if verified else "verification_failed",
        "verified": verified,
        "transaction": result,
        "before": before,
        "after": after,
        "rollback": None,
    }


def network_status(ctx) -> dict:
    """IP interfaces/routes, NetworkManager connections, DNS and listening ports."""
    result = {"status": "ok"}
    for name, argv in {
        "interfaces": ["ip", "-j", "address"],
        "routes": ["ip", "-j", "route"],
        "connections": ["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"],
        "dns": ["resolvectl", "status"],
        "ports": ["ss", "-lntu"],
    }.items():
        result[name] = (
            ctx.run(argv)
            if shutil.which(argv[0])
            else {"status": "missing_dependency", "dependency": argv[0]}
        )
    return result


def network_connect(ctx, uuid: str, rollback_timeout_s: int = 60) -> dict:
    """Activate an existing NetworkManager connection with a timed checkpoint and verification."""
    import uuid as uuid_module

    try:
        uuid_module.UUID(uuid)
    except ValueError as exc:
        raise Fault("invalid_params", "Use a connection UUID from network.status.") from exc
    if not 15 <= rollback_timeout_s <= 600:
        raise Fault("invalid_params", "rollback_timeout_s must be 15..600.")
    bus = [
        "busctl",
        "--system",
        "call",
        "org.freedesktop.NetworkManager",
        "/org/freedesktop/NetworkManager",
        "org.freedesktop.NetworkManager",
    ]
    checkpoint = ctx.run(
        [*bus, "CheckpointCreate", "aouu", "0", str(rollback_timeout_s), "0"],
        admin=True,
        timeout=120,
    )
    if checkpoint["status"] != "ok":
        return checkpoint
    match = re.search(r'o "([^"]+)"', checkpoint["text"])
    if not match:
        return {
            "status": "backend_error",
            "message": "Checkpoint path was not returned.",
            "checkpoint": checkpoint,
        }
    cp = match[1]
    import time

    old_deadline = ctx.deadline
    ctx.deadline = min(old_deadline, time.monotonic() + rollback_timeout_s - 5)
    try:
        result = ctx.run(
            ["nmcli", "--wait", "15", "connection", "up", "uuid", uuid], admin=True, timeout=120
        )
        verify = ctx.run(["nmcli", "-t", "-f", "UUID", "connection", "show", "--active"])
        verified = result["status"] == "ok" and uuid in verify["text"].splitlines()
        if not verified:
            # The checkpoint expires on failure or worker loss; no further auth prompt.
            return {
                "status": result["status"] if result["status"] != "ok" else "verification_failed",
                "checkpoint": cp,
                "rollback_timeout_s": rollback_timeout_s,
                "rollback": "NetworkManager timed checkpoint",
                "activation": result,
            }
        commit = ctx.run([*bus, "CheckpointDestroy", "o", cp], admin=True)
        return {
            "status": "ok" if commit["status"] == "ok" else commit["status"],
            "verified": verified,
            "checkpoint_committed": commit["status"] == "ok",
            "activation": result,
            "commit": commit,
        }
    except Fault as exc:
        return {
            **exc.result(),
            "checkpoint": cp,
            "rollback": "NetworkManager timed checkpoint",
            "rollback_timeout_s": rollback_timeout_s,
        }
    finally:
        ctx.deadline = old_deadline


def storage(ctx) -> dict:
    """Block device inventory including mounts, filesystem, model and size."""
    result = require_ok(
        ctx.run(
            [
                "lsblk",
                "--json",
                "--bytes",
                "--output",
                "NAME,PATH,TYPE,FSTYPE,SIZE,MOUNTPOINTS,MODEL,RO",
            ]
        )
    )
    return {"status": "ok", **json.loads(ctx.store.path(result["output"]).read_bytes())}


def mount(ctx, device: str, operation: Literal["mount", "unmount"] = "mount") -> dict:
    """UDisks mount/unmount with native polkit GUI; return and verify mount state."""
    if not device.startswith("/dev/") or not Path(device).is_block_device():
        raise Fault("invalid_params", "Select a block device from storage.list.")
    result = ctx.run(["udisksctl", operation, "--block-device", device], admin=True, timeout=120)
    if result["status"] != "ok":
        return result
    check = ctx.run(["findmnt", "--json", "--source", device], accepted=(0, 1))
    verified = check["exit_code"] == (0 if operation == "mount" else 1)
    return {
        "status": "ok" if verified else "verification_failed",
        "verified": verified,
        "operation": result,
        "mount": check,
    }


def backup_available():
    return (
        {"status": "available"}
        if os.environ.get("RESTIC_REPOSITORY")
        else {
            "status": "unsupported",
            "reason": "Configure RESTIC_REPOSITORY and a noninteractive restic credential source.",
        }
    )


def backup(ctx, paths: list[str]) -> dict:
    """Create a restic backup, then verify repository metadata with restic check."""
    if not paths:
        raise Fault("invalid_params", "At least one source path is required.")
    result = ctx.run(
        [
            "restic",
            "backup",
            "--json",
            "--",
            *(str(Path(p).expanduser().absolute()) for p in paths),
        ],
        timeout=86400,
    )
    if result["status"] != "ok":
        return result
    check = ctx.run(["restic", "check", "--json"], timeout=86400)
    return {
        "status": "ok" if check["status"] == "ok" else "verification_failed",
        "backup": result,
        "verification": check,
    }


def backup_restore(ctx, snapshot: str, target: str) -> dict:
    """Restore to an empty directory; verify through restic's --verify mode."""
    identifier(snapshot)
    dest = Path(target).expanduser().absolute()
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise Fault("conflict", "Restore target must be an empty directory or a new path.")
    return ctx.run(
        ["restic", "restore", "--verify", snapshot, "--target", str(dest)], timeout=86400
    )


def audio(
    ctx,
    operation: Literal["volume", "mute", "default"],
    target: str = "@DEFAULT_AUDIO_SINK@",
    value: str = "",
) -> dict:
    """Change WirePlumber volume/mute/default, then read the resulting state."""
    if target not in {"@DEFAULT_AUDIO_SINK@", "@DEFAULT_AUDIO_SOURCE@"} and not target.isdigit():
        raise Fault("invalid_params", "target must be a numeric device ID or default sink/source.")
    if operation == "volume" and not re.fullmatch(r"(?:[0-9]{1,2}|100)%", value):
        raise Fault("invalid_params", "volume must be 0%..100%.")
    if operation == "mute" and value not in {"0", "1", "toggle"}:
        raise Fault("invalid_params", "mute value must be 0, 1 or toggle.")
    argv = [
        "wpctl",
        "set-" + {"volume": "volume", "mute": "mute", "default": "default"}[operation],
        target,
    ]
    if operation == "default" and not target.isdigit():
        raise Fault("invalid_params", "Default device requires a numeric target ID.")
    before = ctx.run(["wpctl", "get-volume", target]) if operation != "default" else None
    result = ctx.run([*argv, *([value] if operation != "default" else [])])
    if result["status"] != "ok":
        return result
    check = ctx.run(
        ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"]
        if operation == "default"
        else ["wpctl", "get-volume", target]
    )
    good = check["status"] == "ok"
    if operation == "volume":
        match = re.search(r"Volume: ([0-9.]+)", check["text"])
        good = good and bool(match) and abs(float(match[1]) - int(value[:-1]) / 100) <= 0.015
    elif operation == "mute":
        desired = value == "1" if value != "toggle" else "[MUTED]" not in before["text"]
        good = good and ("[MUTED]" in check["text"]) == desired
    else:
        good = good and re.search(r"id (\d+)", check["text"]) is not None
        good = good and re.search(r"id (\d+)", check["text"])[1] == target
    return {
        "status": "ok" if good else "verification_failed",
        "verified": bool(good),
        "state": check,
        "before": before,
    }


def bluetooth(
    ctx, address: str, operation: Literal["connect", "disconnect", "pair", "trust", "remove"]
) -> dict:
    """BlueZ device operation using bluetoothctl. Pairing may require a human agent."""
    if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", address):
        raise Fault("invalid_params", "Use a Bluetooth MAC address from bluetooth.status.")
    result = ctx.run(["bluetoothctl", "--timeout", "30", operation, address], timeout=40)
    if result["status"] != "ok":
        return result
    check = ctx.run(["bluetoothctl", "info", address])
    expected = {
        "connect": "Connected: yes",
        "disconnect": "Connected: no",
        "pair": "Paired: yes",
        "trust": "Trusted: yes",
        "remove": "not available",
    }[operation]
    good = expected in check["text"]
    return {
        "status": "ok" if good else "verification_failed",
        "verified": good,
        "operation": result,
        "state": check,
    }


def git(
    ctx,
    path: str,
    operation: Literal["status", "diff", "log", "fetch", "pull", "checkout"],
    ref: str = "",
) -> dict:
    """Git operations in an explicit checkout. Never resets or discards local work."""
    argv = {
        "status": ["status", "--short"],
        "diff": ["diff"],
        "log": ["log", "-10", "--oneline"],
        "fetch": ["fetch"],
        "pull": ["pull", "--ff-only"],
        "checkout": ["switch", identifier(ref)] if operation == "checkout" else [],
    }[operation]
    return ctx.run(["git", "-C", str(Path(path).expanduser()), *argv], timeout=3600)


def container(
    ctx, operation: Literal["list", "inspect", "start", "stop", "logs"], target: str = ""
) -> dict:
    """Docker container actions through the installed Docker context."""
    if operation != "list":
        identifier(target)
    argv = {
        "list": ["ps", "-a", "--format=json"],
        "inspect": ["inspect", target],
        "start": ["start", target],
        "stop": ["stop", target],
        "logs": ["logs", "--tail", "100", target],
    }[operation]
    result = ctx.run(["docker", *argv], timeout=120)
    if operation in {"start", "stop"} and result["status"] == "ok":
        check = ctx.run(["docker", "inspect", "--format={{.State.Running}}", target])
        good = (
            check["status"] == "ok" and check["text"].strip() == str(operation == "start").lower()
        )
        return {
            "status": "ok" if good else "verification_failed",
            "verified": good,
            "operation": result,
            "state": check,
        }
    return result


def ssh(ctx, host: str, command: str) -> dict:
    """SSH job using existing host configuration and BatchMode; remote command uses remote shell."""
    identifier(host)
    return ctx.run(["ssh", "-oBatchMode=yes", "-oConnectTimeout=10", host, command], timeout=86400)


def android(
    ctx, serial: str, operation: Literal["shell", "install", "pull", "push"], args: list[str]
) -> dict:
    """ADB on an explicitly selected device. Android permission prompts stay on the device."""
    identifier(serial)
    return ctx.run(["adb", "-s", serial, operation, *args], timeout=3600)


def cli_read(r, name, argv, description):
    def read(ctx):
        return ctx.run(argv)

    r.add(
        name, read, description=description, readonly=True, idempotent=True, dependencies=(argv[0],)
    )


def register(r):
    r.add("package.search", packages, readonly=True, idempotent=True, dependencies=("pacman",))
    r.add(
        "package.change",
        package_change,
        dependencies=("pacman", "pkexec"),
        privilege="GUI admin",
        resources=("package-database",),
        verification="pacman transaction and per-package version readback.",
    )
    r.add("network.status", network_status, readonly=True, idempotent=True)
    r.add(
        "network.connect",
        network_connect,
        dependencies=("nmcli", "busctl", "pkexec"),
        resources=("network",),
        privilege="GUI admin",
        verification="Active connection UUID verified before committing NetworkManager checkpoint.",
        undo="Native timed checkpoint rolls back if verification/commit fails.",
    )
    r.add("storage.list", storage, readonly=True, idempotent=True, dependencies=("lsblk",))
    r.add(
        "storage.mount",
        mount,
        dependencies=("udisksctl", "findmnt"),
        privilege="native polkit GUI",
        resources=lambda p: ("device:" + p["device"],),
    )
    r.add(
        "backup.create",
        backup,
        dependencies=("restic",),
        available=backup_available,
        resources=("restic",),
        verification="restic backup followed by restic check (metadata).",
    )
    r.add(
        "backup.restore",
        backup_restore,
        dependencies=("restic",),
        available=backup_available,
        resources=("restic",),
        verification="restic restore --verify into an empty target.",
    )
    r.add("audio.change", audio, dependencies=("wpctl",), resources=("audio",))
    r.add("bluetooth.change", bluetooth, dependencies=("bluetoothctl",), resources=("bluetooth",))
    # Split read-only and acting Git/container operations at the registry boundary.
    r.add(
        "git.change",
        git,
        dependencies=("git",),
        resources=lambda p: ("git:" + str(Path(p["path"]).resolve()),),
    )

    def git_read(ctx, path: str, operation: Literal["status", "diff", "log"] = "status"):
        return git(ctx, path, operation)

    r.add("git.read", git_read, readonly=True, idempotent=True, dependencies=("git",))
    r.add("container.change", container, dependencies=("docker",), resources=("docker",))

    def container_read(
        ctx, operation: Literal["list", "inspect", "logs"] = "list", target: str = ""
    ):
        return container(ctx, operation, target)

    r.add(
        "container.read", container_read, readonly=True, idempotent=True, dependencies=("docker",)
    )
    r.add("ssh.exec", ssh, dependencies=("ssh",))
    r.add(
        "android.act",
        android,
        dependencies=("adb",),
        resources=lambda p: ("android:" + p["serial"],),
    )
    reads = {
        "audio.status": (["wpctl", "status"], "Audio devices, routes and current defaults."),
        "bluetooth.status": (["bluetoothctl", "devices"], "Known Bluetooth devices."),
        "power.status": (["upower", "--dump"], "Battery and power device measurements."),
        "device.list": (["lsusb"], "USB device inventory."),
        "android.devices": (["adb", "devices", "-l"], "Android devices and authorization states."),
        "vm.list": (
            ["virsh", "list", "--all"],
            "Virtual machines from the configured libvirt connection.",
        ),
        "gpu.status": (
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used",
                "--format=csv,noheader",
            ],
            "NVIDIA measurements when nvidia-smi is installed.",
        ),
        "network.firewall": (
            ["nft", "--json", "list", "ruleset"],
            "Read nftables rules; privileges may be required.",
        ),
        "package.flatpak": (
            ["flatpak", "list", "--columns=application,version,installation"],
            "Installed Flatpak apps.",
        ),
    }
    for name, (argv, description) in reads.items():
        cli_read(r, name, argv, description)
