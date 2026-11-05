"""Registry bindings to the existing validated desktop implementation."""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import threading
from typing import Any, get_type_hints

from agentic_os_mcp.core.registry import Fault
from agentic_os_mcp.core.state import new_id


def selected_session():
    from agentic_os_mcp import session

    try:
        session.ensure_session_env()
    except RuntimeError as exc:
        return {"status": "unsupported", "reason": str(exc)}
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return {"status": "unsupported", "reason": "Select a live Hyprland session explicitly."}
    return {"status": "available"}


def normalize(value, ctx):
    if isinstance(value, list) and value and hasattr(value[0], "type"):
        blocks = []
        for block in value:
            if block.type == "text":
                try:
                    blocks.append(json.loads(block.text))
                except ValueError:
                    blocks.append(block.text)
            elif block.type == "image":
                import base64

                blocks.append(
                    {
                        "artifact": ctx.store.put(base64.b64decode(block.data), block.mimeType),
                        "mime_type": block.mimeType,
                    }
                )
        return {"status": "ok", "content": blocks}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed
        except ValueError:
            # Legacy functions use error strings instead of exceptions in some paths.
            lowered = value.lower()
            failure = any(
                s in lowered
                for s in (
                    "read failed:",
                    "event socket unavailable:",
                    "but no new window appeared",
                    "no accessibility tree",
                    "sequence stopped",
                    "no change seen",
                    "event socket dropped before confirming",
                )
            ) or lowered.startswith(("error", "refused", "failed", "warning", "timeout", "no such"))
            return {
                "status": "failed" if failure else "ok",
                "text": value,
                "verification": "Legacy text response; inspect readback for acting operations.",
            }
    return value


class WindowRefs:
    """Session-scoped compact references; refuse missing/reused compositor identities."""

    def __init__(self):
        self.prefix = new_id("w")[:5]
        self.refs = {}

    @staticmethod
    def identity(client):
        # stableId is authoritative on newer Hyprland; PID birth protects older releases.
        import psutil

        pid = client.get("pid")
        if client.get("stableId") is not None:
            return (client.get("address"), client["stableId"], pid, None)
        birth = None
        if pid:
            with contextlib.suppress(psutil.Error):
                birth = psutil.Process(pid).create_time()
        return (client.get("address"), client.get("stableId"), pid, birth)

    def remember(self, client):
        identity = self.identity(client)
        if identity[1] is None and identity[3] is None:
            raise Fault(
                "unsupported", "Window has neither stableId nor a verifiable process identity."
            )
        for ref, saved in self.refs.items():
            if saved == identity:
                return ref
        ref = self.prefix + str(len(self.refs) + 1)
        self.refs[ref] = identity
        return ref

    def resolve(self, ref):
        from agentic_os_mcp import hyprctl

        if ref not in self.refs:
            raise Fault("stale_reference", "Window reference expired; observe desktop.state again.")
        saved = self.refs[ref]
        for client in hyprctl.query("clients"):
            if client.get("address") == saved[0] and self.identity(client) == saved:
                return saved[0]
        raise Fault("stale_reference", "Window closed or its identity changed; observe again.")

    def args(self, value):
        if isinstance(value, dict):
            return {
                k: self.resolve(v)
                if k in {"target", "window"}
                and isinstance(v, str)
                and v not in {"", "active"}
                and not v.startswith("0x")
                else self.args(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.args(v) for v in value]
        return value

    def snapshot(self, snapshot):
        from agentic_os_mcp import hyprctl

        clients = hyprctl.query("clients")
        mapping = {c["address"]: self.remember(c) for c in clients}
        snapshot = {
            **snapshot,
            "windows": [c for c in snapshot.get("windows", []) if c["address"] in mapping],
        }
        if snapshot.get("active_window") not in mapping:
            snapshot["active_window"] = None

        def shorten(value):
            if isinstance(value, str):
                return mapping.get(value, value)
            if isinstance(value, dict):
                return {k: shorten(v) for k, v in value.items()}
            if isinstance(value, list):
                return [shorten(v) for v in value]
            return value

        return shorten(snapshot)


def register(r):
    from agentic_os_mcp import server

    # Semantic desktop handles and marks share in-process state. Serialize reads too.
    guard = threading.RLock()
    references = WindowRefs()
    mapping = {
        "desktop.state": (server.desktop, True),
        "desktop.ui": (server.ui, True),
        "desktop.screenshot": (server.screenshot, True),
        "desktop.zoom": (server.zoom, True),
        "desktop.marks": (server.marks, True),
        "desktop.binds": (server.binds, True),
        "desktop.wait": (server.wait_for, True),
        "desktop.pointer": (server.pointer, False),
        "desktop.keyboard": (server.keyboard, False),
        "desktop.click": (server.click_ui, False),
        "desktop.hypr": (server.hypr, False),
        "desktop.launch": (server.launch, False),
        "desktop.sequence": (server.sequence, False),
    }

    def bind(name, fn, readonly, needs_session=True, override=None):
        hints = get_type_hints(fn)
        params = {
            p.name: (
                hints.get(p.name, Any),
                ... if p.default is inspect.Parameter.empty else p.default,
            )
            for p in inspect.signature(fn).parameters.values()
        }
        if override:
            params.update(override)

        def handler(ctx, **kwargs):
            with guard:
                kwargs = references.args(kwargs)
                value = fn(**kwargs)
                if name == "desktop.state":
                    value = references.snapshot(value)
                result = normalize(value, ctx)
                if isinstance(result, dict) and not readonly:
                    result.setdefault("verified", False)
                return result

        r.add(
            name,
            handler,
            params=params,
            description=inspect.getdoc(fn) or name,
            readonly=readonly,
            idempotent=readonly,
            resources=("desktop-seat",),
            available=selected_session if needs_session else None,
        )

    for name, (fn, readonly) in mapping.items():
        bind(name, fn, readonly)

    def focus(ctx, window: str):
        """Focus an observed compact window reference and verify activewindow immediately."""
        address = references.resolve(window)
        result = normalize(server.hypr(action="focus_window", target=address), ctx)
        actual = server.hyprctl.query("activewindow").get("address")
        good = actual == address
        return {
            "status": "ok" if good else "verification_failed",
            "verified": good,
            "window": window,
            "result": result,
        }

    def close(ctx, window: str):
        """Close an observed window reference and verify that compositor no longer lists it."""
        address = references.resolve(window)
        result = normalize(server.hypr(action="close_window", target=address), ctx)
        good = not any(c.get("address") == address for c in server.hyprctl.query("clients"))
        return {
            "status": "ok" if good else "verification_failed",
            "verified": good,
            "result": result,
        }

    for name, fn in (("desktop.focus", focus), ("desktop.close", close)):
        r.add(
            name,
            fn,
            resources=("desktop-seat",),
            available=selected_session,
            verification="Read compositor active window or client inventory after dispatch.",
        )

    # Mixed legacy tools get distinct read and edit contracts; observe cannot smuggle edits.
    def canvas_read(ctx, **kwargs):
        return normalize(server.canvas(action="read", **kwargs), ctx)

    hints = get_type_hints(server._canvas_readonly)
    params = {
        p.name: (hints.get(p.name, Any), ... if p.default is inspect.Parameter.empty else p.default)
        for p in inspect.signature(server._canvas_readonly).parameters.values()
    }
    r.add(
        "canvas.read",
        canvas_read,
        params=params,
        readonly=True,
        idempotent=True,
        description="Read saved Canvas cards and connections without desktop access.",
    )
    bind("canvas.edit", server.canvas, False, False)
    from agentic_os_mcp import kanban

    if kanban.configured():
        for name, fn, readonly in (
            ("kanban.read", server.kanban_read, True),
            ("kanban.wait", server.kanban_wait, True),
            ("kanban.add", server.kanban_add, False),
            ("kanban.update", server.kanban_update, False),
        ):
            bind(name, fn, readonly, False)
