import asyncio
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from omnimcp import hyprctl, server
from omnimcp import input as hinput
from omnimcp.adapters import build_registry
from omnimcp.core.engine import Engine
from omnimcp.core.fastmcp import hide_validation_input
from omnimcp.core.protocol import validate
from omnimcp.core.registry import Fault
from omnimcp.core.state import Store


def call_entrypoint(tool, args, profile):
    async def go():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "omnimcp"],
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
                "OMNIMCP_PROFILE": profile,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "OMNIMCP_BACKGROUND": "1",
                "OMNIMCP_DRYRUN": "1",
            },
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool, args)

    return asyncio.run(go())


def reject_every_tool(profile):
    async def go():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "omnimcp"],
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
                "OMNIMCP_PROFILE": profile,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "OMNIMCP_BACKGROUND": "1",
                "OMNIMCP_DRYRUN": "1",
            },
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            results = [
                (tool.name, await session.call_tool(tool.name, {}))
                for tool in tools.tools if tool.inputSchema.get("required")
            ]
            return results

    return asyncio.run(go())


def test_real_legacy_entrypoint_redacts_invalid_tool_input():
    result = call_entrypoint(
        "canvas", {"path": "/tmp/a.canvas", "action": "R2_SECRET_MARKER"}, "legacy"
    )
    message = " ".join(block.text for block in result.content if hasattr(block, "text"))
    assert result.isError
    assert "action" in message
    assert "R2_SECRET_MARKER" not in message


def test_real_compact_entrypoint_redacts_invalid_tool_input():
    result = call_entrypoint(
        "observe", {"action": "desktop", "offset": "R2_SECRET_MARKER"}, "compact"
    )
    message = " ".join(block.text for block in result.content if hasattr(block, "text"))
    assert result.isError
    assert "offset" in message
    assert "R2_SECRET_MARKER" not in message


def test_real_entrypoints_reject_missing_required_args_for_every_listed_tool():
    for profile in ("legacy", "compact"):
        for name, result in reject_every_tool(profile):
            message = " ".join(block.text for block in result.content if hasattr(block, "text"))
            assert result.isError, name
            assert "required" in message.lower() or "field required" in message.lower(), name


def test_legacy_readonly_listed_tools_reject_bad_typed_params_before_body(monkeypatch):
    monkeypatch.setattr(server, "READONLY", True)
    for variable in ("OMNIMCP_READONLY", "OMNIMCP_BACKGROUND", "OMNIMCP_DRYRUN"):
        monkeypatch.setenv(variable, "1")
    for variable in (
        "HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"
    ):
        monkeypatch.delenv(variable, raising=False)
    app = server.build_app()

    async def go():
        listed = await app.list_tools()
        assert listed
        results = []
        for tool in app._tool_manager._tools.values():
            model = tool.fn_metadata.arg_model
            schema = model.model_json_schema().get("properties", {})
            baseline = {
                field: _sample(spec)
                for field, spec in schema.items()
                if model.model_fields[field].is_required()
            }
            object.__setattr__(tool, "fn", lambda **_: (_ for _ in ()).throw(
                RuntimeError("BODY_REACHED")
            ))
            for field in schema:
                bad = _invalid_value(model, baseline, field)
                assert bad is not None, f"no invalid marker value for {tool.name}.{field}"
                try:
                    result = await app.call_tool(tool.name, {**baseline, field: bad})
                    message = " ".join(
                        block.text for block in result.content if hasattr(block, "text")
                    )
                except Exception as exc:
                    message = str(exc)
                results.append((tool.name, field, message))
        return results

    results = asyncio.run(go())
    assert results
    for name, field, message in results:
        assert field in message, name
        assert "invalid" in message.lower() or "input should" in message.lower(), name
        assert "BODY_REACHED" not in message, name
        assert "R2_SECRET_MARKER" not in message, name


def _sample(schema):
    if "default" in schema:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    if "anyOf" in schema:
        return _sample(schema["anyOf"][0])
    kind = schema.get("type")
    return {"string": "sample", "integer": 0, "number": 0.0,
            "boolean": False, "array": [], "object": {}}.get(kind)


def _invalid_value(model, baseline, field):
    for candidate in ("R2_SECRET_MARKER", {"R2_SECRET_MARKER": "x"}, ["R2_SECRET_MARKER"]):
        try:
            model.model_validate({**baseline, field: candidate})
        except ValidationError as exc:
            if any(error["loc"] == (field,) for error in exc.errors(include_input=False)):
                return candidate
    return None


def test_compact_entrypoint_validates_discover_observe_act_and_workflow():
    cases = [
        ("discover", {"offset": "R2_SECRET_MARKER"}, "offset"),
        ("observe", {"action": "desktop", "offset": "R2_SECRET_MARKER"}, "offset"),
        ("act", {"action": "desktop", "background": "R2_SECRET_MARKER"}, "background"),
        ("workflow", {"steps": "R2_SECRET_MARKER"}, "steps"),
    ]
    for tool, args, field in cases:
        result = call_entrypoint(tool, args, "compact")
        message = " ".join(block.text for block in result.content if hasattr(block, "text"))
        assert result.isError
        assert field in message
        assert "R2_SECRET_MARKER" not in message


def test_rpc_observe_offset_validation_redacts_value():
    try:
        validate({"op": "observe", "action": "desktop", "offset": "R2_SECRET_MARKER"})
    except Fault as exc:
        assert "offset" in str(exc)
        assert "R2_SECRET_MARKER" not in str(exc)
    else:
        raise AssertionError("expected invalid offset")


def test_engine_file_read_offset_error_redacts_value(tmp_path):
    target = tmp_path / "read-me.txt"
    target.write_text("safe content")
    store = Store(tmp_path / "state")
    engine = Engine(build_registry(), store)
    try:
        result = engine.request({
            "op": "observe",
            "action": "file.read",
            "params": {"path": str(target), "offset": "R2_SECRET_MARKER"},
        })
    finally:
        engine.close()
    assert result["status"] == "invalid_params"
    assert "offset" in result["message"]
    assert "R2_SECRET_MARKER" not in result["message"]


def test_incompatible_fastmcp_internals_fail_loudly():
    class BrokenApp:
        _tool_manager = object()

    with pytest.raises(AttributeError, match="_tools"):
        hide_validation_input(BrokenApp())


def test_hyprctl_failure_does_not_echo_command_arguments(monkeypatch):
    monkeypatch.setattr(hyprctl.shutil, "which", lambda _: "/usr/bin/hyprctl")
    monkeypatch.setattr(
        hyprctl.subprocess,
        "run",
        lambda *args, **kwargs: type("Proc", (), {
            "stdout": "", "stderr": "R2_SECRET_MARKER", "returncode": 1
        })(),
    )
    try:
        hyprctl._run("dispatch", "sendshortcut", "R2_SECRET_MARKER")
    except hyprctl.HyprctlError as exc:
        assert "R2_SECRET_MARKER" not in str(exc)
    else:
        raise AssertionError("expected hyprctl failure")


def test_wtype_failure_does_not_echo_stderr(monkeypatch):
    monkeypatch.setattr(hinput.shutil, "which", lambda _: "/usr/bin/wtype")
    monkeypatch.setattr(
        hinput.subprocess,
        "run",
        lambda *args, **kwargs: type("Proc", (), {
            "stderr": "R2_SECRET_MARKER", "returncode": 1
        })(),
    )
    try:
        hinput._wtype(["-"], stdin="R2_SECRET_MARKER")
    except hinput.InputError as exc:
        assert "R2_SECRET_MARKER" not in str(exc)
    else:
        raise AssertionError("expected wtype failure")


def test_hyprctl_timeout_redacts_command_arguments(monkeypatch):
    monkeypatch.setattr(hyprctl.shutil, "which", lambda _: "/usr/bin/hyprctl")

    def timeout(*args, **kwargs):
        raise hyprctl.subprocess.TimeoutExpired(args[0], 5)

    monkeypatch.setattr(hyprctl.subprocess, "run", timeout)
    try:
        hyprctl._run("dispatch", "R2_SECRET_MARKER")
    except hyprctl.HyprctlError as exc:
        assert "R2_SECRET_MARKER" not in str(exc)
    else:
        raise AssertionError("expected hyprctl timeout")


def test_wtype_timeout_is_wrapped_without_command_details(monkeypatch):
    monkeypatch.setattr(hinput.shutil, "which", lambda _: "/usr/bin/wtype")

    def timeout(*args, **kwargs):
        raise hinput.subprocess.TimeoutExpired(args[0], 15)

    monkeypatch.setattr(hinput.subprocess, "run", timeout)
    try:
        hinput._wtype(["R2_SECRET_MARKER"])
    except hinput.InputError as exc:
        assert "R2_SECRET_MARKER" not in str(exc)
    else:
        raise AssertionError("expected wtype timeout")
