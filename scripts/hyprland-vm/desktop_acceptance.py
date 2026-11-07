#!/usr/bin/env python3
"""Exercise the installed legacy MCP server against a real Hyprland session."""

import asyncio
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ARTIFACTS = Path(os.environ.get("OMNIMCP_ARTIFACT_DIR", "/home/tester/artifacts"))
TOKEN = uuid.uuid4().hex[:12]
FIXTURE_CLASS = "omnimcp-accept-" + TOKEN
MARKER = ARTIFACTS / ("fixture-" + TOKEN + ".txt")
MARKER_VALUE = "omnimcp-keyboard-" + TOKEN
RESULT = {"status": "failed", "checks": {}, "fixture_class": FIXTURE_CLASS}


def response(result):
    if result.isError:
        raise RuntimeError("MCP tool error: " + str(result.content))
    if result.structuredContent is not None:
        value = result.structuredContent
        if isinstance(value, dict) and set(value) == {"result"}:
            value = value["result"]
        if not isinstance(value, list):
            return value
        content = value
    else:
        content = result.content
    for item in content:
        kind = item.get("type") if isinstance(item, dict) else getattr(item, "type", "")
        text = item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
        if kind == "text":
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                pass
    return "\n".join(
        item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
        for item in content
    )


async def run():
    RESULT["hyprland_version"] = subprocess.check_output(
        ["hyprctl", "version"], text=True, timeout=10
    ).strip()
    env = dict(os.environ, OMNIMCP_PROFILE="legacy", OMNIMCP_SCREENSHOT_MODE="file")
    params = StdioServerParameters(
        command="/opt/omnimcp-venv/bin/python", args=["-m", "omnimcp.server"], env=env
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await asyncio.wait_for(session.initialize(), 25)
        tools = await asyncio.wait_for(session.list_tools(), 15)
        names = {t.name for t in tools.tools}
        required = {"desktop", "launch", "screenshot", "keyboard", "pointer", "hypr"}
        if not required <= names:
            raise RuntimeError(f"missing legacy tools: {sorted(required - names)}")
        RESULT["checks"]["legacy_stdio"] = "passed"

        async def call(name, args=None, timeout=30):
            return response(await asyncio.wait_for(session.call_tool(name, args or {}), timeout))

        before = await call("desktop")
        if (
            not isinstance(before, dict)
            or not before.get("monitors")
            or not isinstance(before.get("windows"), list)
        ):
            raise RuntimeError(f"invalid desktop snapshot: {before!r}")
        RESULT["checks"]["desktop"] = {
            "status": "passed",
            "monitors": len(before["monitors"]),
            "windows": len(before["windows"]),
        }
        if not shutil.which("foot"):
            raise RuntimeError("foot terminal is required")
        address = None
        try:
            command = f"foot --app-id {FIXTURE_CLASS} /bin/sh -i"
            launched = await call(
                "launch", {"command": command, "wait_s": 25, "background": False}, timeout=40
            )
            if not isinstance(launched, dict) or not launched.get("address"):
                raise RuntimeError(f"fixture launch failed: {launched!r}")
            address = launched["address"]
            state = await call("desktop")
            match = [
                w
                for w in state["windows"]
                if w.get("address") == address and w.get("class") == FIXTURE_CLASS
            ]
            if len(match) != 1:
                raise RuntimeError(f"launched window identity mismatch: {launched!r}, {state!r}")
            RESULT["checks"]["launch"] = {"status": "passed", "address": address}

            await call("pointer", {"action": "move", "x": 320, "y": 240, "background": False})
            cursor = json.loads(
                subprocess.check_output(["hyprctl", "-j", "cursorpos"], text=True, timeout=10)
            )
            assert abs(cursor["x"] - 320) <= 1 and abs(cursor["y"] - 240) <= 1, cursor
            await call("pointer", {"action": "click", "x": 320, "y": 240, "background": False})
            RESULT["checks"]["pointer"] = {"status": "passed", "actual_cursor": cursor}

            capture = await call("screenshot", {"lossless": True}, timeout=40)
            if not isinstance(capture, dict) or not capture.get("path"):
                raise RuntimeError(f"missing screenshot metadata/path: {capture!r}")
            source = Path(capture["path"])
            data = source.read_bytes()
            if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
                raise RuntimeError("screenshot is not a PNG with an IHDR")
            width, height = struct.unpack(">II", data[16:24])
            if width < 320 or height < 200 or len(data) < 1024:
                raise RuntimeError(f"screenshot too small: {width}x{height}, {len(data)} bytes")
            dest = ARTIFACTS / "desktop-acceptance.png"
            dest.write_bytes(data)
            RESULT["checks"]["screenshot"] = {
                "status": "passed",
                "path": str(dest),
                "width": width,
                "height": height,
                "bytes": len(data),
            }

            typed = (
                "printf '%s\\n' " + shlex.quote(MARKER_VALUE) + " | tee " + shlex.quote(str(MARKER))
            )
            await call(
                "keyboard",
                {"action": "type", "text": typed, "window": address, "background": False},
            )
            await call(
                "keyboard",
                {"action": "key", "keys": "enter", "window": address, "background": False},
            )
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if MARKER.exists() and MARKER.read_text().strip() == MARKER_VALUE:
                    break
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError("typed command marker missing or incorrect")
            RESULT["checks"]["keyboard"] = {
                "status": "passed",
                "marker": str(MARKER),
                "value": MARKER_VALUE,
            }
            after_capture = await call("screenshot", {"lossless": True}, timeout=40)
            after_data = Path(after_capture["path"]).read_bytes()
            assert after_data[:8] == b"\x89PNG\r\n\x1a\n" and after_data != data
            dest.write_bytes(after_data)
            RESULT["checks"]["screenshot"]["bytes"] = len(after_data)
            RESULT["checks"]["screenshot"]["after_keyboard"] = True

            closed = await call("hypr", {"action": "close_window", "target": address})
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                state = await call("desktop")
                if all(w.get("address") != address for w in state["windows"]):
                    break
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError(f"fixture remains in compositor: {closed!r}")
            RESULT["checks"]["close"] = {"status": "passed", "response": closed}
            address = None
        finally:
            if address:
                try:
                    state = await call("desktop", timeout=10)
                    if any(
                        w.get("address") == address and w.get("class") == FIXTURE_CLASS
                        for w in state.get("windows", [])
                    ):
                        await call(
                            "hypr", {"action": "close_window", "target": address}, timeout=10
                        )
                except Exception as exc:
                    RESULT["cleanup_error"] = repr(exc)


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(asyncio.wait_for(run(), 150))
        RESULT["status"] = "passed"
    except BaseException as exc:
        RESULT["error"] = repr(exc)
        RESULT["traceback"] = traceback.format_exc()
    path = ARTIFACTS / "desktop-acceptance.json"
    path.write_text(json.dumps(RESULT, indent=2) + "\n")
    print(json.dumps(RESULT, indent=2), flush=True)
    return 0 if RESULT["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
