"""Codex quota reader: protocol, sanitization, and read-only registration."""

import asyncio
import json
import os

import pytest


@pytest.fixture
def codex_child(tmp_path, monkeypatch):
    """Install a fake codex executable that speaks the app-server JSONL protocol."""
    import omnimcp.codex_usage as usage

    child = tmp_path / "codex"
    child.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        "capture = os.environ['CODEX_CAPTURE']\n"
        "mode = os.environ.get('CODEX_FAKE_MODE', 'success')\n"
        "with open(capture, 'a') as log:\n"
        "    log.write('PID ' + str(os.getpid()) + '\\n'); log.flush()\n"
        "    for line in sys.stdin:\n"
        "        request = json.loads(line)\n"
        "        log.write(json.dumps(request) + '\\n'); log.flush()\n"
        "        method = request.get('method')\n"
        "        if method == 'initialize':\n"
        "            result = {'serverInfo': {'name': 'codex', 'version': 'fixture'}}\n"
        "        elif method == 'account/rateLimits/read':\n"
        "            if mode == 'timeout':\n"
        "                time.sleep(30); continue\n"
        "            if mode == 'malformed':\n"
        "                print('{malformed', flush=True); continue\n"
        "            if mode == 'oversized':\n"
        "                print(' ' * 1048577, flush=True); continue\n"
        "            if mode == 'invalid_fields':\n"
        "                result = {'rateLimits': {'limitId':'codex','primary':\n"
        "                    {'usedPercent':'25','windowDurationMins':300}}}\n"
        "                print(json.dumps({'jsonrpc':'2.0','id':request['id'],\n"
        "                    'result':result}), flush=True)\n"
        "                continue\n"
        "            if mode == 'secret_error':\n"
        "                print(json.dumps({'jsonrpc':'2.0','id':request['id'],\n"
        "                    'error':{'code':-32000,\n"
        "                            'message':'TOKEN_SECRET diagnostic'}}), flush=True)\n"
        "                continue\n"
        "            result = {'rateLimitsByLimitId': {\n"
        "                'codex': {'limitId':'codex','planType':'plus',\n"
        "                    'primary': {'usedPercent':25,'windowDurationMins':300,\n"
        "                                'resetsAt': 2000000000},\n"
        "                    'secondary': {'usedPercent':61,'windowDurationMins':10080,\n"
        "                                  'resetsAt': 2000003600}},\n"
        "                'other': {'limitId':'other','planType':'team',\n"
        "                    'primary': {'usedPercent':10,'windowDurationMins':60,\n"
        "                                'resetsAt': None},\n"
        "                    'secondary': None,\n"
        "                    'vendorSecret':'MUST_NOT_ESCAPE'}},\n"
        "                'rateLimits': {'limitId':'codex','planType':'plus',\n"
        "                    'primary': {'usedPercent':25,'windowDurationMins':300,\n"
        "                                'resetsAt': 2000000000}}}\n"
        "        else:\n"
        "            continue\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':request['id'],\n"
        "            'result':result}), flush=True)\n"
    )
    child.chmod(0o700)
    capture = tmp_path / "requests.jsonl"
    monkeypatch.setenv("CODEX_CAPTURE", str(capture))
    monkeypatch.delenv("CODEX_FAKE_MODE", raising=False)
    monkeypatch.setattr(usage.shutil, "which", lambda name: str(child) if name == "codex" else None)
    return usage, capture


def test_read_usage_handshakes_and_normalizes_multiple_windows(codex_child, monkeypatch):
    usage, capture = codex_child
    monkeypatch.setenv("TZ", "UTC")

    result = usage.read_usage(timezone="UTC")

    assert result["status"] == "ok"
    assert result["timezone"] == "UTC"
    assert result["checked_at"]
    by_id = {limit["limit_id"]: limit for limit in result["limits"]}
    assert set(by_id) == {"codex", "other"}  # the codex entry in both raw fields is merged
    codex = by_id["codex"]
    assert codex["plan_type"] == "plus"
    assert [window["kind"] for window in codex["windows"]] == ["five_hour", "weekly"]
    assert codex["windows"][0]["used_percent"] == 25
    assert codex["windows"][0]["remaining_percent"] == 75
    assert codex["windows"][0]["resets_at"] == 2000000000
    from datetime import datetime

    assert datetime.fromisoformat(codex["windows"][0]["reset_utc"]).utcoffset().total_seconds() == 0
    local_offset = datetime.fromisoformat(codex["windows"][0]["reset_local"]).utcoffset()
    assert local_offset.total_seconds() == 0
    assert by_id["other"]["windows"][0]["kind"] == "other"
    assert by_id["other"]["windows"][0]["resets_at"] is None
    assert by_id["other"]["windows"][0]["reset_utc"] is None
    assert len(by_id["other"]["windows"]) == 1  # absent and explicit null windows are skipped
    assert "vendorSecret" not in json.dumps(result)

    lines = capture.read_text().splitlines()
    requests = [json.loads(line) for line in lines if line.startswith("{")]
    assert requests[0]["method"] == "initialize" and requests[0]["id"] == 1
    assert requests[1]["method"] == "initialized" and "id" not in requests[1]
    assert requests[2]["method"] == "account/rateLimits/read" and requests[2]["id"] == 2
    assert len(requests) == 3  # no generation, tools or other account operations


def test_read_usage_timeout_is_reported(codex_child, monkeypatch):
    usage, capture = codex_child
    monkeypatch.setenv("CODEX_FAKE_MODE", "timeout")

    result = usage.read_usage(timeout_s=0.15)

    assert result["status"] == "timeout"
    child_pid = int(capture.read_text().splitlines()[0].removeprefix("PID "))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_read_usage_does_not_expose_backend_diagnostics(codex_child, monkeypatch):
    usage, _ = codex_child
    monkeypatch.setenv("CODEX_FAKE_MODE", "secret_error")

    result = usage.read_usage()

    assert result["status"] in {"backend_error", "auth_required"}
    assert "TOKEN_SECRET" not in json.dumps(result)


def test_read_usage_rejects_malformed_protocol_output(codex_child, monkeypatch):
    usage, _ = codex_child
    monkeypatch.setenv("CODEX_FAKE_MODE", "malformed")

    result = usage.read_usage(timeout_s=0.5)

    assert result["status"] == "invalid_response"


@pytest.mark.parametrize("mode", ["invalid_fields", "oversized"])
def test_read_usage_rejects_invalid_or_oversized_result(codex_child, monkeypatch, mode):
    usage, _ = codex_child
    monkeypatch.setenv("CODEX_FAKE_MODE", mode)

    result = usage.read_usage(timeout_s=1)

    assert result["status"] == "invalid_response"


def test_json_facade_is_compact_and_rejects_invalid_parameters(codex_child):
    usage, _ = codex_child

    compact = usage.codex_usage(timezone="UTC")
    decoded = json.loads(compact)
    assert decoded["status"] == "ok"
    assert "\n" not in compact
    assert json.loads(usage.codex_usage(timeout_s=0))["status"] == "invalid_params"


def test_legacy_tool_is_registered_in_readonly_mode_without_structured_output(monkeypatch):
    from omnimcp import server

    monkeypatch.setattr(server, "READONLY", True)
    tools = asyncio.run(server.build_app().list_tools())
    tool = next(tool for tool in tools if tool.name == "codex_usage")
    assert tool.outputSchema is None
    assert tool.annotations.readOnlyHint is True


def test_compact_registry_exposes_readonly_codex_usage(codex_child):
    from omnimcp.adapters import build_registry

    action = build_registry().get("codex.usage")
    assert action.readonly is True
    result = action.handler(None, **action.validate({"timezone": "UTC"}))
    assert result["status"] == "ok"
    assert result["limits"][0]["windows"][0]["remaining_percent"] == 75


def test_stdio_discovery_and_call(codex_child):
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _, capture = codex_child
    env = {**os.environ, "PATH": str(capture.parent) + os.pathsep + os.environ["PATH"]}

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            # Real stdio transport; no compositor initialization needed for account reads.
            args=["-c", "from omnimcp.server import build_app; build_app().run()"],
            env=env,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert "codex_usage" in {tool.name for tool in tools.tools}
            result = await session.call_tool("codex_usage", {"timezone": "Asia/Ulaanbaatar"})
            assert not result.isError
            assert len(result.content) == 1
            assert not result.structuredContent
            data = json.loads(result.content[0].text)
            assert data["status"] == "ok"
            assert data["limits"][0]["windows"][0]["remaining_percent"] == 75
            assert data["limits"][0]["windows"][0]["reset_local"].endswith("+08:00")

    asyncio.run(run())
