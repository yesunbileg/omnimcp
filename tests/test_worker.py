"""Real subprocess, Unix socket, MCP protocol and PTY integration on isolated state."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from omnimcp.core.client import rpc


class Worker:
    def __init__(self, root):
        self.env = {
            **os.environ,
            "OMNIMCP_STATE_DIR": str(root / "state"),
            "OMNIMCP_SOCKET": str(root / "worker.sock"),
            "OMNIMCP_PROFILE": "compact",
        }
        for key in ("OMNIMCP_READONLY", "OMNIMCP_DRYRUN", "OMNIMCP_BROWSER_COMMAND"):
            self.env.pop(key, None)
        self.proc = None
        self.start()

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "omnimcp.core.worker"],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                pytest.fail(self.proc.communicate()[1].decode())
            if Path(self.env["OMNIMCP_SOCKET"]).exists():
                try:
                    with socket.socket(socket.AF_UNIX) as probe:
                        probe.settimeout(0.2)
                        probe.connect(self.env["OMNIMCP_SOCKET"])
                        probe.sendall(b'{"op":"discover","limit":1}\n')
                        if b"items" in probe.recv(16384):
                            return
                except OSError:
                    pass
            time.sleep(0.02)
        pytest.fail("Worker startup timed out")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        out, err = self.proc.communicate()
        assert b"Traceback" not in err, (out, err)


@pytest.fixture
def worker(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="aos-test-") as temp:
        value = Worker(Path(temp))
        monkeypatch.setenv("OMNIMCP_SOCKET", value.env["OMNIMCP_SOCKET"])
        yield value
        value.stop()


def wait_job(ref, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = rpc({"op": "job", "job_id": ref})
        if result.get("status") not in {"running", "queued"}:
            return result
        time.sleep(0.03)
    pytest.fail("Job timeout")


def sync_action(name, params):
    return rpc({"op": "act", "action": name, "params": params, "background": False})


def test_mcp_wire_single_text_content_and_disconnect_keeps_job(worker):
    async def launch():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "omnimcp", "--profile", "compact"],
            env=worker.env,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert len(tools.tools) == 7
            result = await session.call_tool(
                "act",
                {
                    "action": "command.exec",
                    "params": {
                        "argv": [
                            sys.executable,
                            "-c",
                            'import time; time.sleep(.3); print("survived")',
                        ]
                    },
                },
            )
            assert not result.isError and result.structuredContent is None
            assert len(result.content) == 1 and result.content[0].type == "text"
            return json.loads(result.content[0].text)["job_id"]

    ref = asyncio.run(launch())
    completed = wait_job(ref)
    assert completed["status"] == "succeeded"
    assert completed["result"]["text"] == "survived\n"


def test_restart_does_not_replay_inflight_change(worker):
    ref = rpc({"op": "act", "action": "event.wait", "params": {"since": 10**9, "timeout_s": 30}})[
        "job_id"
    ]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if rpc({"op": "job", "job_id": ref})["status"] == "running":
            break
        time.sleep(0.02)
    worker.proc.kill()
    worker.proc.wait(timeout=5)
    worker.start()
    assert rpc({"op": "job", "job_id": ref})["status"] == "interrupted"
    assert rpc({"op": "events", "since": 0})["items"]


def test_pty_has_controlling_terminal_and_survives_connections(worker):
    terminal = sync_action("pty.start", {"argv": ["/bin/bash", "--noprofile", "--norc"]})
    assert terminal["status"] == "ok", terminal
    ref = terminal["ref"]
    sync_action("pty.write", {"ref": ref, "text": 'printf "PTY_%s\\n" "OK"; exit\n'})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = rpc({"op": "observe", "action": "pty.status", "params": {"ref": ref}})
        if state.get("state") == "exited":
            break
        time.sleep(0.03)
    assert state["exit_code"] == 0, state
    output = rpc({"op": "artifact", "ref": terminal["output"]})["data"]
    assert "PTY_OK" in output
    assert "no job control" not in output and "cannot set terminal process group" not in output


def test_file_write_restore_end_to_end(worker, tmp_path):
    path = tmp_path / "file"
    path.write_text("original")
    read = rpc({"op": "observe", "action": "file.read", "params": {"path": str(path)}})
    write = sync_action(
        "file.write", {"path": str(path), "text": "changed", "expected_revision": read["revision"]}
    )
    assert write["verified"] and path.read_text() == "changed"
    assert sync_action(write["undo"]["action"], write["undo"]["params"])["verified"]
    assert path.read_text() == "original"


def test_malformed_socket_requests_do_not_break_worker(worker):
    import socket

    path = worker.env["OMNIMCP_SOCKET"]
    for raw in (b"not-json\n", b"[]\n", b'{"op":"unknown"}\n'):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.connect(path)
            sock.sendall(raw)
            sock.shutdown(socket.SHUT_WR)
            sock.recv(16384)
    assert "items" in rpc({"op": "discover", "limit": 2})
