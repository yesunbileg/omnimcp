"""Actual stdio MCP serialization and lifecycle; isolated board, no desktop input."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_compact_kanban_stdio_lifecycle(tmp_path):
    path = tmp_path / "board.md"
    original = "---\nkanban-plugin: board\n---\n\n## Todo\n\n- [ ] Keep instructions\n\n## Done\n"
    path.write_text(original)

    async def exercise():
        env = {**os.environ, "OMNIMCP_KANBAN_FILE": str(path),
               "OMNIMCP_READONLY": "0", "OMNIMCP_DRYRUN": "0",
               "XDG_RUNTIME_DIR": str(tmp_path)}
        params = StdioServerParameters(command=sys.executable, args=["-m", "omnimcp"],
                                       env=env)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert "append_text" in tools["kanban_update"].inputSchema["properties"]
            assert all(tools[n].outputSchema is None for n in tools if n.startswith("kanban_"))

            async def call(name, **args):
                result = await client.call_tool(name, args)
                assert not result.isError, result.content
                assert result.structuredContent is None
                assert len(result.content) == 1 and result.content[0].type == "text"
                text = result.content[0].text
                assert "\n" not in text  # JSON strings escape embedded newlines
                return json.loads(text)

            before = await call("kanban_read", query="Keep")
            task_id = before["tasks"][0]["id"]
            done = await call("kanban_update", task_id=task_id,
                              expected_revision=before["revision"], column="Done", checked=True,
                              append_text="Үр дүн: verified https://example.org/")
            assert "text" not in done["task"]
            assert done["task"]["column"] == "Done" and done["task"]["checked"]
            current = await call("kanban_read", task_id=done["task"]["id"])
            assert current["tasks"][0]["text"] == (
                "Keep instructions\nҮр дүн: verified https://example.org/")
            assert current["revision"] == done["revision"]
            stale = await client.call_tool("kanban_update", {
                "task_id": done["task"]["id"], "expected_revision": before["revision"],
                "append_text": "Cannot overwrite"})
            assert stale.isError
            waited = await call("kanban_wait", revision=current["revision"], timeout_s=0)
            assert waited["changed"] is False
            added = await call("kanban_add", column="Todo", text="New card",
                               expected_revision=current["revision"])
            assert "text" not in added["task"] and not added["task"]["checked"]

    asyncio.run(exercise())
    assert "Cannot overwrite" not in path.read_text()
