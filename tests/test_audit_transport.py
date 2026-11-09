"""Regressions for verified transport audit findings."""

import asyncio
import base64
import json
import os
import socket
import threading
import time
from types import SimpleNamespace

from mcp.types import ImageContent


def test_legacy_image_tools_disable_structured_output_and_convert_once():
    from omnimcp.legacy_transport import build_app

    image_data = base64.b64encode(b"x" * 700_000).decode()
    image = ImageContent(type="image", data=image_data, mimeType="image/png")

    async def screenshot():
        return [image]

    async def zoom():
        return [image]

    async def state() -> dict[str, str]:
        return {"status": "ok"}

    desktop = SimpleNamespace(
        READONLY=True,
        __version__="test",
        _instructions="instructions",
        _OBSERVE_TOOLS=[screenshot, zoom, state],
        _TITLES={"screenshot": "Screenshot", "zoom": "Zoom", "state": "State"},
    )
    app = build_app(desktop)

    async def run():
        tools = {tool.name: tool for tool in await app.list_tools()}
        assert tools["screenshot"].outputSchema is None
        assert tools["zoom"].outputSchema is None
        assert tools["state"].outputSchema is not None
        for name in ("screenshot", "zoom"):
            result = await app.call_tool(name, {})
            assert len(result) == 1
            assert result[0].type == "image"

    asyncio.run(run())


def test_compact_maps_application_fault_to_mcp_error_without_changing_json(monkeypatch):
    from omnimcp import compact

    monkeypatch.delenv("OMNIMCP_READONLY", raising=False)
    monkeypatch.setattr(
        compact,
        "rpc",
        lambda request: {"status": "invalid_params", "message": "bad input", "field": "x"},
    )

    async def inline(fn, *args):
        return fn(*args)

    monkeypatch.setattr(compact.asyncio, "to_thread", inline)
    app = compact.build_app()

    async def run():
        result = await app.call_tool("observe", {"action": "desktop"})
        assert result.isError is True
        assert json.loads(result.content[0].text) == {
            "status": "invalid_params",
            "message": "bad input",
            "field": "x",
        }

    asyncio.run(run())


def test_compact_keeps_queued_and_running_results_non_errors(monkeypatch):
    from omnimcp import compact

    monkeypatch.delenv("OMNIMCP_READONLY", raising=False)
    monkeypatch.setattr(compact, "rpc", lambda request: {"status": "queued", "job_id": "j1"})

    async def inline(fn, *args):
        return fn(*args)

    monkeypatch.setattr(compact.asyncio, "to_thread", inline)
    app = compact.build_app()

    async def run():
        result = await app.call_tool("act", {"action": "command.exec"})
        assert json.loads(result[0].text) == {"status": "queued", "job_id": "j1"}

    asyncio.run(run())


def test_compact_job_state_is_not_mcp_error(monkeypatch):
    from omnimcp import compact

    monkeypatch.delenv("OMNIMCP_READONLY", raising=False)
    monkeypatch.setattr(
        compact, "rpc", lambda request: {"status": "failed", "job_id": "j1", "result": {}}
    )

    async def inline(fn, *args):
        return fn(*args)

    monkeypatch.setattr(compact.asyncio, "to_thread", inline)
    app = compact.build_app()

    async def run():
        result = await app.call_tool("job", {"job_id": "j1"})
        assert json.loads(result[0].text)["status"] == "failed"

    asyncio.run(run())


def test_click_readback_failure_stays_typed_through_both_result_shapes(monkeypatch):
    from omnimcp import hyprctl, server
    from omnimcp.adapters.desktop import normalize
    from omnimcp.legacy_result import LegacyContent

    for name in ("guard_client", "guard_auth_client", "guard_session_lock"):
        monkeypatch.setattr(server.trust, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(server.a11y, "connect", lambda: object())
    monkeypatch.setattr(server.a11y, "has_action", lambda *args: True)
    monkeypatch.setattr(server.a11y, "action_name", lambda *args: "click")
    monkeypatch.setattr(server.a11y, "current_value", lambda *args: {"pressed": False})
    monkeypatch.setattr(server.a11y, "do_action", lambda *args: True)
    monkeypatch.setattr(server, "_seat_now", lambda: None)
    monkeypatch.setattr(server, "_seat_report", lambda seat: (False, ""))
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    monkeypatch.setattr(hyprctl, "query", lambda _: [{"address": "0x1"}])
    monkeypatch.setattr(hyprctl, "snapshot", lambda: {})
    client = {"address": "0x1", "class": "Fixture"}
    control = {"_svc": "svc", "_path": "/button", "_field": False, "role": "button"}

    plain = server._click_in_background(client, control, "button", "none", False)
    assert normalize(plain, None)["status"] == "failed"
    fused = server._click_in_background(client, control, "button", "desktop", False)
    assert isinstance(fused, LegacyContent)
    assert normalize(fused, None)["status"] == "failed"


def test_compact_fault_status_taxonomy_and_unknown_status(monkeypatch):
    from omnimcp import compact

    monkeypatch.delenv("OMNIMCP_READONLY", raising=False)
    response = {"status": "ok"}
    monkeypatch.setattr(compact, "rpc", lambda request: dict(response))

    async def inline(fn, *args):
        return fn(*args)

    monkeypatch.setattr(compact.asyncio, "to_thread", inline)
    app = compact.build_app()

    async def run():
        for status in (
            "busy",
            "auth_cancelled",
            "auth_timeout",
            "cancellation_pending",
            "timeout_pending",
            "future_worker_fault",
        ):
            response.clear()
            response.update({"status": status, "detail": "kept"})
            result = await app.call_tool("act", {"action": "system.snapshot"})
            assert result.isError is True
            assert result.content[0].text == json.dumps(
                {"status": status, "detail": "kept"}, separators=(",", ":")
            )
        for status in ("failed", "cancelled", "interrupted", "queued", "running"):
            response.clear()
            response.update({"status": status})
            result = await app.call_tool("job", {"job_id": "j1"})
            assert json.loads(result[0].text)["status"] == status

    asyncio.run(run())


def test_compact_application_fault_is_error_on_real_mcp_protocol(tmp_path):
    import os
    import subprocess
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    socket_path = tmp_path / "worker.sock"
    env = {
        **os.environ,
        "OMNIMCP_SOCKET": str(socket_path),
        "OMNIMCP_STATE_DIR": str(tmp_path / "state"),
        "OMNIMCP_PROFILE": "compact",
    }
    worker = subprocess.Popen(
        [sys.executable, "-m", "omnimcp.core.worker"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not socket_path.exists():
            if worker.poll() is not None:
                raise AssertionError(worker.communicate()[1].decode())
            time.sleep(0.02)

        async def exercise():
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "omnimcp", "--profile", "compact"], env=env
            )
            async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
                await client.initialize()
                result = await client.call_tool("observe", {"action": "no.such.action"})
                assert result.isError is True
                expected = {
                    "status": "unsupported",
                    "message": "Unknown action: no.such.action; use discover.",
                }
                assert result.content[0].text == json.dumps(
                    expected, ensure_ascii=False, separators=(",", ":")
                )

        asyncio.run(exercise())
    finally:
        worker.terminate()
        worker.wait(timeout=10)
        _, stderr = worker.communicate()
        assert b"Traceback" not in stderr


def test_rpc_read_timeout_is_client_timeout_and_does_not_claim_worker_absent(tmp_path, monkeypatch):
    from omnimcp.core.client import rpc

    path = tmp_path / "worker.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    os.chmod(path, 0o600)  # Match the real worker; the client rejects looser modes.
    listener.listen(1)
    accepted = threading.Event()

    def serve():
        conn, _ = listener.accept()
        with conn:
            accepted.set()
            time.sleep(0.25)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setenv("OMNIMCP_SOCKET", str(path))
    result = rpc({"op": "job", "job_id": "j1"}, timeout=0.03)
    listener.close()
    thread.join(timeout=1)
    assert accepted.is_set()
    assert result["status"] == "client_timeout"
    assert "worker install/status" not in result["message"]
    assert "unknown" in result["message"].lower() or "inspect" in result["message"].lower()


def test_rpc_disconnect_after_request_send_is_unknown_outcome(tmp_path, monkeypatch):
    from omnimcp.core.client import rpc

    path = tmp_path / "worker.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    os.chmod(path, 0o600)  # Match the real worker; the client rejects looser modes.
    listener.listen(1)
    received = threading.Event()

    def serve():
        conn, _ = listener.accept()
        with conn:
            assert conn.recv(1024)
            received.set()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setenv("OMNIMCP_SOCKET", str(path))
    result = rpc({"op": "act", "action": "command.exec"}, timeout=1)
    listener.close()
    thread.join(timeout=1)
    assert received.is_set()
    assert result["status"] == "client_disconnected"
    assert "outcome is unknown" in result["message"]
    assert "install/status" not in result["message"]


def test_legacy_readback_failure_is_typed_at_source():
    from omnimcp.legacy_result import LegacyFailure
    from omnimcp.server import _read_back

    result = _read_back("before", "before", "typed")
    assert isinstance(result, LegacyFailure)
    assert result == "no change seen"


def test_legacy_plain_text_is_unverified_unless_typed_failure():
    from omnimcp.adapters.desktop import normalize
    from omnimcp.legacy_result import LegacyContent, LegacyFailure, LegacyUnverified

    arbitrary = normalize("Window opened", None)
    assert arbitrary["status"] == "ok"
    assert arbitrary["verified"] is False
    assert arbitrary["outcome"] == "unverified"
    assert arbitrary["text"] == "Window opened"
    warning = normalize("warning: the title contains an ordinary word", None)
    assert warning["status"] == "ok" and warning["verified"] is False
    failure = normalize(LegacyFailure("Не болсон"), None)
    assert failure["status"] == "failed" and failure["text"] == "Не болсон"
    uncertain = normalize(LegacyUnverified("close sent"), None)
    assert uncertain["status"] == "ok" and uncertain["outcome"] == "unverified"
    fused = normalize(
        LegacyContent([SimpleNamespace(type="text", text="response")], "failed"), None
    )
    assert fused["status"] == "failed" and fused["verified"] is False
    structured = {"status": "ok", "value": 1}
    assert normalize(json.dumps(structured), None) == structured
