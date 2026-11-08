"""The public product name is consistent across installed and MCP interfaces."""

import asyncio
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

ROOT = Path(__file__).resolve().parents[1]


def test_distribution_and_both_command_entrypoints_use_the_canonical_brand():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["name"] == "OmniMCP-linux"
    assert project["scripts"]["OmniMCP"] == project["scripts"]["omnimcp"]


@pytest.mark.parametrize("command", ["OmniMCP", "omnimcp"])
def test_installed_command_aliases_report_the_same_brand(command):
    executable = Path(sys.executable).parent / command
    result = subprocess.run(
        [str(executable), "--version"], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("OmniMCP ")


@pytest.mark.parametrize("profile", ["legacy", "compact"])
def test_real_mcp_initialization_reports_canonical_brand(profile, monkeypatch):
    from omnimcp import compact, server

    monkeypatch.setenv("OMNIMCP_READONLY", "1")
    monkeypatch.setattr(server, "READONLY", True)
    app = server.build_app() if profile == "legacy" else compact.build_app()

    async def exercise():
        async with create_connected_server_and_client_session(app._mcp_server) as client:
            result = await client.initialize()
            assert result.serverInfo.name == "OmniMCP"

    asyncio.run(exercise())


def test_plugin_and_skill_display_names_are_canonical():
    plugin = ROOT / "packaging/codex/omnimcp"
    portable = json.loads((plugin / "plugin.json").read_text())
    codex = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
    assert portable["extensions"]["com.openai"]["interface"]["displayName"] == "OmniMCP"
    assert codex["interface"]["displayName"] == "OmniMCP"
    skill = (ROOT / "skills/omnimcp/agents/openai.yaml").read_text()
    assert 'display_name: "OmniMCP"' in skill


@pytest.mark.parametrize("runtime", ["OmniMCP", "omnimcp", "explicit", "launcher-on-path"])
def test_plugin_launcher_selects_external_runtime_and_refuses_recursive_paths(runtime, tmp_path):
    launcher = ROOT / "packaging/codex/omnimcp/bin/OmniMCP"
    bin_dir = tmp_path / "runtime with spaces"
    bin_dir.mkdir()
    executable = bin_dir / ("OmniMCP" if runtime == "OmniMCP" else "omnimcp")
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    executable.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin")
    env.pop("OMNIMCP_BIN", None)
    if runtime == "explicit":
        env["OMNIMCP_BIN"] = str(executable)
    elif runtime == "launcher-on-path":
        env["PATH"] = f"{launcher.parent}:{env['PATH']}"
    result = subprocess.run(
        [str(launcher), "argument with spaces", "--version"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    if runtime == "launcher-on-path":
        # Both command names resolve to this launcher; require an explicit runtime.
        assert result.returncode == 127
        assert result.stderr.startswith("OmniMCP plugin:")
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["argument with spaces", "--version"]


@pytest.mark.parametrize("command", ["OmniMCP", "omnimcp"])
def test_plugin_launcher_rejects_both_self_aliases(command):
    launcher = ROOT / "packaging/codex/omnimcp/bin" / command
    result = subprocess.run(
        [str(launcher)],
        capture_output=True,
        text=True,
        env=dict(os.environ, OMNIMCP_BIN=str(launcher)),
        timeout=5,
    )
    assert result.returncode == 127
    assert result.stderr.startswith("OmniMCP plugin:")
