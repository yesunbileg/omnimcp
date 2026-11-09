"""Removed board integrations stay absent across transports and packaging."""

import asyncio
import importlib.util
import os
import subprocess
import sys

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from omnimcp import server
from omnimcp.adapters import build_registry
from omnimcp.core.engine import Engine
from omnimcp.core.state import Store


@pytest.fixture
def configured_old_board(tmp_path, monkeypatch):
    path = tmp_path / "user-board.md"
    path.write_text("user content must remain untouched")
    monkeypatch.setenv("OMNIMCP_KANBAN_FILE", str(path))
    yield path
    assert path.read_text() == "user content must remain untouched"


@pytest.mark.parametrize("readonly", [False, True])
def test_legacy_discovery_has_no_board_tools(configured_old_board, readonly, monkeypatch):
    monkeypatch.setattr(server, "READONLY", readonly)
    app = server.build_app()
    names = {tool.name for tool in asyncio.run(app.list_tools())}
    assert "canvas" not in names
    assert not any(name.startswith("kanban_") for name in names)
    assert "obsidian" not in app.instructions.lower()
    assert "kanban" not in app.instructions.lower()


def test_removed_actions_are_unsupported_by_the_core(configured_old_board, tmp_path):
    store = Store(tmp_path / "state")
    engine = Engine(build_registry(), store)
    try:
        for action in (
            "canvas.read",
            "canvas.edit",
            "kanban.read",
            "kanban.wait",
            "kanban.add",
            "kanban.update",
        ):
            result = engine.request(
                {"op": "act", "action": action, "params": {}, "background": False}
            )
            assert result["status"] == "unsupported", (action, result)
    finally:
        engine.close()
        store.close()


@pytest.mark.parametrize("module", ["omnimcp.canvas", "omnimcp.kanban"])
def test_removed_modules_are_not_importable(module):
    assert importlib.util.find_spec(module) is None


def test_removed_cli_command_is_rejected_before_reading_user_file(tmp_path):
    path = tmp_path / "user.canvas"
    path.write_bytes(b"leave this file alone")
    result = subprocess.run(
        [sys.executable, "-m", "omnimcp", "canvas", str(path)],
        capture_output=True,
        text=True,
        env=os.environ,
        timeout=5,
    )
    assert result.returncode == 2, result.stderr
    assert path.read_bytes() == b"leave this file alone"


def test_removed_names_return_unknown_tool_on_actual_mcp(configured_old_board):
    app = server.build_app()

    async def exercise():
        async with create_connected_server_and_client_session(app._mcp_server) as client:
            await client.initialize()
            for name in ("canvas", "kanban_read", "kanban_add", "kanban_update", "kanban_wait"):
                result = await client.call_tool(name, {})
                assert result.isError
                message = " ".join(block.text for block in result.content if block.type == "text")
                assert "unknown tool" in message.lower(), (name, message)

    asyncio.run(exercise())
