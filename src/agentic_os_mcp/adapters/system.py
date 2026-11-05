"""System measurements, systemd units and journal access."""

from __future__ import annotations

import contextlib
import json
import os
import platform
import re
from typing import Literal

import psutil

from agentic_os_mcp.core.execution import require_ok
from agentic_os_mcp.core.registry import Fault


def snapshot(ctx) -> dict:
    """CPU counters, RAM, filesystems, thermal sensors, boot and session identity."""
    temperatures = {}
    with contextlib.suppress(AttributeError, OSError):
        temperatures = {
            k: [v._asdict() for v in values] for k, values in psutil.sensors_temperatures().items()
        }
    disks = []
    for part in psutil.disk_partitions():
        try:
            disks.append(
                {
                    "path": part.mountpoint,
                    "type": part.fstype,
                    **psutil.disk_usage(part.mountpoint)._asdict(),
                }
            )
        except OSError:
            continue
    return {
        "status": "ok",
        "kernel": platform.release(),
        "boot_time": psutil.boot_time(),
        "cpu_count": psutil.cpu_count(),
        "load": os.getloadavg(),
        "cpu_seconds": psutil.cpu_times()._asdict(),
        "memory": psutil.virtual_memory()._asdict(),
        "swap": psutil.swap_memory()._asdict(),
        "disks": disks,
        "temperatures": temperatures,
        "session": {
            k: os.environ.get(k)
            for k in (
                "XDG_SESSION_ID",
                "XDG_SESSION_TYPE",
                "WAYLAND_DISPLAY",
                "HYPRLAND_INSTANCE_SIGNATURE",
            )
        },
    }


def unit_name(unit):
    if not re.fullmatch(r"[A-Za-z0-9_.:@\\-]+", unit) or unit.startswith("-"):
        raise Fault("invalid_params", "Invalid unit name.")
    return unit


def base(scope):
    return ["systemctl", "--no-pager", *(["--user"] if scope == "user" else [])]


def services(
    ctx,
    scope: Literal["user", "system"] = "user",
    kind: Literal["service", "timer", "socket", "target"] = "service",
) -> list[dict]:
    """List loaded service/timer/socket/target units with their real states."""
    result = require_ok(
        ctx.run([*base(scope), "list-units", "--all", "--output=json", f"--type={kind}"])
    )
    return json.loads(ctx.store.path(result["output"]).read_bytes())


def status(ctx, unit: str, scope: Literal["user", "system"] = "user") -> dict:
    """Read load, active, substate, enabled state, result and main PID for one unit."""
    result = require_ok(
        ctx.run(
            [
                *base(scope),
                "show",
                unit_name(unit),
                "--property=Id,LoadState,ActiveState,SubState,UnitFileState,Result,MainPID",
            ]
        )
    )
    fields = dict(line.split("=", 1) for line in result["text"].splitlines() if "=" in line)
    if fields.get("LoadState") == "not-found":
        raise Fault("not_found", "Unit does not exist.", unit=unit)
    return {"status": "ok", **fields}


def change(
    ctx,
    unit: str,
    operation: Literal["start", "stop", "restart", "reload", "enable", "disable"],
    scope: Literal["user", "system"] = "user",
) -> dict:
    """Change a systemd unit, then independently read and verify its state."""
    before = status(ctx, unit, scope)
    result = ctx.run(
        [*base(scope), operation, unit_name(unit)], admin=scope == "system", timeout=120
    )
    if result["status"] != "ok":
        return result
    after = status(ctx, unit, scope)
    good = (
        after.get("ActiveState") == ("inactive" if operation == "stop" else "active")
        if operation in {"start", "stop", "restart", "reload"}
        else after.get("UnitFileState")
        in (
            {"enabled", "enabled-runtime"}
            if operation == "enable"
            else {"disabled", "static", "indirect"}
        )
    )
    # Restore only the dimensions the operation changed. A restart cannot restore the old process.
    undo = (
        ("enable" if before.get("UnitFileState", "").startswith("enabled") else "disable")
        if (operation in {"enable", "disable"})
        else ("start" if before.get("ActiveState") == "active" else "stop")
    )
    return {
        "status": "ok" if good else "verification_failed",
        "before": before,
        "after": after,
        "verified": good,
        "undo": {
            "action": "service.change",
            "params": {"unit": unit, "operation": undo, "scope": scope},
        },
    }


def logs(
    ctx,
    unit: str = "",
    scope: Literal["user", "system"] = "user",
    since: str = "",
    lines: int = 50,
    cursor: str = "",
) -> dict:
    """Read bounded journal records with journal continuation cursor and retained full output."""
    if not 1 <= lines <= 1000:
        raise Fault("invalid_params", "lines must be 1..1000.")
    argv = [
        "journalctl",
        "--no-pager",
        "--output=json",
        f"--lines={lines}",
        *(["--user"] if scope == "user" else []),
    ]
    if unit:
        argv += ["--unit", unit_name(unit)]
    if since:
        argv += ["--since", since]
    if cursor:
        argv += ["--after-cursor", cursor]
    result = require_ok(ctx.run(argv))
    data = ctx.store.path(result["output"]).read_text(errors="replace")
    records = [json.loads(line) for line in data.splitlines() if line.startswith("{")]
    return {
        "status": "ok",
        "items": [
            {
                k: v
                for k, v in row.items()
                if k
                in {
                    "MESSAGE",
                    "PRIORITY",
                    "__REALTIME_TIMESTAMP",
                    "_SYSTEMD_UNIT",
                    "_SYSTEMD_USER_UNIT",
                }
            }
            for row in records
        ],
        "cursor": records[-1].get("__CURSOR") if records else cursor,
        "output": result["output"],
    }


def wait_event(ctx, since: int, kind: str = "", timeout_s: float = 30) -> dict:
    """Wait for a worker event after a cursor, without repeated AI round trips."""
    import time

    if since < 0 or not 0 <= timeout_s <= 3600:
        raise Fault("invalid_params", "since>=0 and timeout_s=0..3600.")
    deadline = time.monotonic() + timeout_s
    while True:
        result = ctx.store.events(since, 50, kind)
        if result["items"]:
            return {"status": "ok", **result}
        if time.monotonic() >= deadline:
            return {"status": "timeout", **result}
        ctx.sleep(0.1)


def register(r):
    r.add("system.snapshot", snapshot, readonly=True, idempotent=True)
    r.add("service.list", services, readonly=True, idempotent=True, dependencies=("systemctl",))
    r.add("service.status", status, readonly=True, idempotent=True, dependencies=("systemctl",))
    r.add(
        "service.change",
        change,
        dependencies=("systemctl",),
        privilege="GUI when scope=system",
        resources=lambda p: (f"service:{p['scope']}:{p['unit']}",),
        undo=(
            "Returned service.change restores previous active/enabled state, not old process state."
        ),
        verification="Read systemctl show after operation; compare ActiveState or UnitFileState.",
    )
    r.add("log.read", logs, readonly=True, idempotent=True, dependencies=("journalctl",))
    r.add("event.wait", wait_event, readonly=True, idempotent=True)
