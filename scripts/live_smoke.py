#!/usr/bin/env python3
"""Reversible end-to-end smoke against an installed worker and this user's session.

Creates only its own transient user service and temporary files. Optional desktop
check launches a separate hidden Kitty and closes only that observed fixture.
No admin prompts, package changes, network changes or user tab switches.
"""

import argparse
import asyncio
import contextlib
import http.server
import json
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(args):
    checks = {}
    async with (
        stdio_client(
            StdioServerParameters(command=args.command, args=["--profile", "compact"])
        ) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        async def call(tool, **kwargs):
            result = await session.call_tool(tool, kwargs)
            assert not result.isError, result
            assert len(result.content) == 1 and result.structuredContent is None
            return json.loads(result.content[0].text)

        async def act(action, params):
            return await call("act", action=action, params=params, background=False)

        tools = await session.list_tools()
        assert len(tools.tools) == 7
        checks["mcp_tools"] = len(tools.tools)
        measure = await call("observe", action="system.snapshot", fields=["memory", "load"])
        assert measure["memory"]["total"] > 0
        checks["system"] = "passed"
        for directory, label in [(Path.home() / ".cache", "home"), (Path.cwd(), "workspace")]:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".aos-smoke-", dir=directory) as temp:
                path = Path(temp) / "config"
                path.write_text("original Монгол\n")
                path.chmod(0o640)
                mode = stat.S_IMODE(path.stat().st_mode)
                first = await call("observe", action="file.read", params={"path": str(path)})
                changed = await act(
                    "file.patch",
                    {
                        "path": str(path),
                        "before": "original",
                        "after": "changed",
                        "expected_revision": first["revision"],
                    },
                )
                assert changed.get("verified") and path.read_text() == "changed Монгол\n", changed
                assert stat.S_IMODE(path.stat().st_mode) == mode
                restored = await act(changed["undo"]["action"], changed["undo"]["params"])
                assert restored["verified"] and path.read_text() == "original Монгол\n"
                assert stat.S_IMODE(path.stat().st_mode) == mode
                fs = subprocess.check_output(
                    ["findmnt", "-T", temp, "-n", "-o", "FSTYPE"], text=True
                ).strip()
                checks["file_" + label] = {"status": "passed", "filesystem": fs, "mode": oct(mode)}
        job = await call("act", action="command.exec", params={"argv": ["uname", "-r"]})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            done = await call("job", job_id=job["job_id"])
            if done["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.05)
        assert done["status"] == "succeeded", done
        checks["command_job"] = "passed"
        name = "omnimcp-smoke-" + uuid.uuid4().hex[:8] + ".service"
        subprocess.run(
            ["systemd-run", "--user", "--unit", name, "/usr/bin/sleep", "60"],
            check=True,
            capture_output=True,
        )
        try:
            before = await call("observe", action="service.status", params={"unit": name})
            restarted = await act("service.restart", {"unit": name})
            assert restarted["verified"] and restarted["after"]["ActiveState"] == "active", (
                restarted
            )
            assert before["MainPID"] != restarted["after"]["MainPID"]
            checks["user_service_restart"] = "passed"
        finally:
            subprocess.run(["systemctl", "--user", "stop", name], capture_output=True)
        for action in [
            "package.search",
            "storage.list",
            "network.status",
            "audio.status",
            "app.list",
        ]:
            params = {"query": "python"} if action == "package.search" else {}
            result = await call("observe", action=action, params=params, limit=2)
            checks[action] = result.get("status", "passed")
            assert result.get("status", "ok") in {
                "ok",
                "missing_dependency",
                "permission_required",
            }, result
        if args.desktop:
            before = await call("observe", action="desktop.state")
            if before.get("status") in {"unsupported", "missing_dependency"}:
                checks["desktop"] = before
            else:
                assert before.get("windows") is not None, before
                active = before["active_window"]
                capture = await call(
                    "observe", action="desktop.screenshot", params={"region": "0,0,8x8"}
                )
                # The next call immediately confirms focus is still the user's original window.
                after = await call("observe", action="desktop.state")
                assert active == after["active_window"]
                assert capture.get("status") == "ok", capture
                checks["screenshot_preserves_focus"] = "passed"
                if shutil.which("kitty"):
                    unique = "omnimcp-smoke-" + uuid.uuid4().hex[:8]
                    launched = await act(
                        "desktop.launch",
                        {
                            "command": f"kitty --class {unique} /usr/bin/sleep 30",
                            "background": True,
                        },
                    )
                    assert "address" in launched, launched
                    state = await call("observe", action="desktop.state")
                    fixture = next(w for w in state["windows"] if w["class"] == unique)
                    try:
                        assert active == state["active_window"], "Fixture unexpectedly moved focus"
                    finally:
                        closed = await act("desktop.close", {"window": fixture["address"]})
                    assert closed["verified"], closed
                    checks["desktop_launch_close"] = "passed"
        if args.browser:
            tab = await act("browser.tab", {"operation": "new"})
            assert tab["status"] == "ok", tab
            tab_text = "\n".join(c.get("text", "") for c in tab["content"])
            selected = re.search(r"- (\d+): \(current\)", tab_text)
            assert selected, tab
            index = int(selected[1])
            tabs = await call("observe", action="browser.tabs")
            checks["browser_tabs"] = tabs["status"]
            result = await act("browser.navigate", {"tab": index, "url": args.browser_url})
            assert result["status"] == "ok", result
            snapshot = await call("observe", action="browser.snapshot")
            assert snapshot["status"] == "ok", snapshot
            assert "omnimcp Fixture" in json.dumps(snapshot), snapshot
            checks["browser_navigation_snapshot"] = "passed"
            text = "\n".join(c.get("text", "") for c in snapshot["content"])
            field = re.search(r'textbox "Name" \[ref=([^\]]+)\]', text)
            button = re.search(r'button "Save" \[ref=([^\]]+)\]', text)
            assert field and button, text
            filled = await act(
                "browser.fill", {"tab": index, "ref": field[1], "element": "Name", "text": "Codex"}
            )
            assert filled["status"] == "ok", filled
            clicked = await act(
                "browser.click", {"tab": index, "ref": button[1], "element": "Save"}
            )
            assert clicked["status"] == "ok", clicked
            verified = await call("observe", action="browser.snapshot")
            assert "Saved Codex" in json.dumps(verified), verified
            checks["browser_form_fill_click_readback"] = "passed"
            await act("browser.tab", {"operation": "close", "tab": index})
        events = await call("events", limit=2)
        assert events["items"]
        checks["event_cursor"] = "passed"
    return checks


@contextlib.contextmanager
def fixture_server():
    page = b"""<!doctype html><title>omnimcp Fixture</title>
    <label>Name <input id='name'></label>
    <button onclick="document.getElementById('result').textContent=
    'Saved '+document.getElementById('name').value">Save</button>
    <p id='result' aria-live='polite'></p>"""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", default=str(Path.home() / ".local/bin/omnimcp"))
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--browser-url", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with contextlib.ExitStack() as stack:
        if args.browser and not args.browser_url:
            args.browser_url = stack.enter_context(fixture_server())
        result = asyncio.run(main(args))
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n")
