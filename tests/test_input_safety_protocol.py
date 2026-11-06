"""Safety regressions over real MCP stdio, with all desktop I/O replaced."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = r'''
from omnimcp import server as s

actions = []
s.safety.touch = lambda *a: None
s.trust.guard_seat = lambda: None
s.trust.remember_seat = lambda: None
s.trust.guard_session_lock = lambda *a: ""
s.trust.guard_keyboard_layer = lambda *a: ""
s.hyprctl.query = lambda cmd: {"address": "0xauth"} if cmd == "activewindow" else []
s.hinput.move = lambda *a: actions.append("move")
s.hinput.type_text = lambda text: actions.append("type")

class Stream:
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def wait_for(self, *args): return None
    def drain(self, *args): return []
    def close(self): pass

s.events.EventStream = Stream
app = s.build_app()

@app.tool()
def probe_actions() -> dict[str, list[str]]:
    return {"actions": actions}

@app.tool()
def probe_disable_monitoring() -> str:
    def unavailable():
        raise s.events.EventError("isolated socket failure")
    s.events.EventStream = unavailable
    return "disabled"

app.run()
'''


def test_input_failures_stop_actions_over_stdio(tmp_path):
    async def exercise():
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("OMNIMCP_")}
        env.update(OMNIMCP_BACKGROUND="0", OMNIMCP_AUTH_GUARD="1",
                   XDG_RUNTIME_DIR=str(tmp_path))
        params = StdioServerParameters(command=sys.executable, args=["-c", SERVER], env=env)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            for monitor in (True, False):
                result = await client.call_tool("sequence", {
                    "steps": [{"op": "wait_for", "event": "window_open", "timeout_s": 1},
                              {"op": "pointer", "action": "move", "x": 1, "y": 2}],
                    "stop_on_change": monitor, "then": "none",
                })
                assert not result.isError, result.content
                assert "stopped after 1/2" in result.content[0].text
                assert "timeout" in result.content[0].text

            typed = await client.call_tool("keyboard", {"action": "type", "text": "sample"})
            assert typed.isError
            assert "not found" in typed.content[0].text

            await client.call_tool("probe_disable_monitoring", {})
            refused = await client.call_tool("sequence", {
                "steps": [{"op": "pointer", "action": "move", "x": 1, "y": 2}],
                "then": "none",
            })
            assert refused.isError
            assert "isolated socket failure" in refused.content[0].text
            actions = await client.call_tool("probe_actions", {})
            assert not actions.isError
            assert json.loads(actions.content[0].text) == {"actions": []}

    asyncio.run(exercise())
