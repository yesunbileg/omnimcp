"""Compatibility is applied before imports and preserves the stdio protocol."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def clean_env(tmp_path, **extra):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AGENTIC_OS_", "OMNIMCP_"))
        and k
        not in (
            "HYPRLAND_INSTANCE_SIGNATURE",
            "WAYLAND_DISPLAY",
            "DBUS_SESSION_BUS_ADDRESS",
            "DISPLAY",
        )
    }
    env.update(
        XDG_RUNTIME_DIR=str(tmp_path), PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")
    )
    env.update(extra)
    return env


def test_import_maps_generic_variables_and_warns_without_values(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "import os, omnimcp; print(os.environ['OMNIMCP_FUTURE'])"],
        env=clean_env(tmp_path, AGENTIC_OS_FUTURE="SECRET_VALUE"),
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert result.stdout == "SECRET_VALUE\n"
    assert "AGENTIC_OS_FUTURE" in result.stderr and "OMNIMCP_FUTURE" in result.stderr
    assert "SECRET_VALUE" not in result.stderr


def test_explicit_new_empty_value_wins(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "import os, omnimcp; print(repr(os.environ['OMNIMCP_FUTURE']))"],
        env=clean_env(tmp_path, AGENTIC_OS_FUTURE="SECRET_VALUE", OMNIMCP_FUTURE=""),
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert result.stdout == "''\n"
    assert "AGENTIC_OS_FUTURE" in result.stderr and "OMNIMCP_FUTURE" in result.stderr
    assert "SECRET_VALUE" not in result.stderr


def test_warning_escapes_control_characters_in_names(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "import omnimcp"],
        env=clean_env(tmp_path, **{"AGENTIC_OS_BAD\n\x1b": "secret-value"}),
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert result.stderr.count("\n") == 1
    assert "\x1b" not in result.stderr
    assert "secret-value" not in result.stderr
    assert r"\n\x1b" in result.stderr


def test_new_nonempty_value_wins(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "import os, omnimcp; print(os.environ['OMNIMCP_FUTURE'])"],
        env=clean_env(tmp_path, AGENTIC_OS_FUTURE="old-secret", OMNIMCP_FUTURE="new-value"),
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert result.stdout == "new-value\n"
    assert "old-secret" not in result.stderr
    assert "AGENTIC_OS_FUTURE" in result.stderr


def test_legacy_trust_settings_reach_consumers(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from omnimcp import trust; "
            "print(trust._explicit_scope()); print(trust._auth_guard_on())",
        ],
        env=clean_env(tmp_path, AGENTIC_OS_CONFINE="launched", AGENTIC_OS_AUTH_GUARD="0"),
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "launched" in result.stdout
    assert result.stdout.rstrip().endswith("False")
    assert "AGENTIC_OS_CONFINE" in result.stderr
    assert "AGENTIC_OS_AUTH_GUARD" in result.stderr


def test_cli_help_warns_on_stderr(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "omnimcp", "--help"],
        env=clean_env(tmp_path, AGENTIC_OS_FUTURE="SECRET_VALUE"),
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "AGENTIC_OS_FUTURE" in result.stderr and "OMNIMCP_FUTURE" in result.stderr
    assert "SECRET_VALUE" not in result.stderr + result.stdout
    assert "AGENTIC_OS_FUTURE" not in result.stdout


def test_legacy_readonly_mcp_lists_no_acting_tools(tmp_path):
    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "omnimcp"],
            env=clean_env(tmp_path, AGENTIC_OS_READONLY="1", OMNIMCP_PROFILE="legacy"),
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            return {tool.name for tool in (await client.list_tools()).tools}

    names = asyncio.run(asyncio.wait_for(run(), timeout=15))
    assert "desktop" in names
    assert not names.intersection(
        {"pointer", "keyboard", "click_ui", "hypr", "launch", "sequence", "clipboard", "opencode"}
    )
