"""Owner CLI acceptance against a real daemon, jobs and MCP stdio bridge."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_worker import Worker

from omnimcp.core.client import rpc


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    instance = Worker(tmp_path)
    monkeypatch.setenv("OMNIMCP_SOCKET", instance.env["OMNIMCP_SOCKET"])
    try:
        yield instance
    finally:
        instance.stop()


def test_owner_cli_stops_stubborn_job_and_can_race_normal_cancel(daemon, tmp_path):
    marker = tmp_path / "ready.json"
    code = (
        "import json,os,signal,sys,time,psutil; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "open(sys.argv[1],'w').write(json.dumps([os.getpid(),psutil.Process().create_time()])); "
        "time.sleep(60)"
    )
    submitted = rpc({"op": "act", "action": "command.exec", "params": {
        "argv": [sys.executable, "-c", code, str(marker)]}})
    assert submitted["status"] == "queued", submitted
    job = submitted["job_id"]
    pid = birth = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if marker.exists():
                try:
                    pid, birth = json.loads(marker.read_text())
                    break
                except json.JSONDecodeError:
                    pass
            time.sleep(.02)
        assert pid is not None, "Child did not install its SIGTERM handler"
        before = rpc({"op": "job", "job_id": job})
        assert before["status"] == "running" and before["pid"] == pid
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancellation = pool.submit(rpc, {"op": "job", "job_id": job, "cancel": True})
            cli = subprocess.run(
                [sys.executable, "-m", "omnimcp", "worker", "stop-all"],
                env=daemon.env, capture_output=True, text=True, timeout=10,
            )
            assert cancellation.result(timeout=2)["status"] == "cancellation_requested"
        assert time.monotonic() - started < 10
        assert cli.returncode == 0, cli.stderr
        counts = json.loads(cli.stdout)
        assert counts["status"] == "ok"
        assert counts["cancelled"] == 1 and counts["groups_terminated"] == 1
        assert counts["killed"] == 1 and counts["threads_still_busy"] == 0
        assert rpc({"op": "job", "job_id": job})["status"] == "cancelled"
        try:
            child = psutil.Process(pid)
            assert child.create_time() != birth or child.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
        repeated = rpc({"op": "worker_stop_all"}, timeout=10)
        assert repeated == {"status": "ok", "cancelled": 0, "groups_terminated": 0,
                            "killed": 0, "threads_still_busy": 0}
        assert rpc({"op": "observe", "action": "system.snapshot"})["memory"]["total"] > 0
    finally:
        # Only the fixture process with its recorded birth time may be cleaned up.
        if pid is not None:
            try:
                child = psutil.Process(pid)
                if child.create_time() == birth and child.status() != psutil.STATUS_ZOMBIE:
                    os.kill(pid, signal.SIGKILL)
            except (psutil.NoSuchProcess, ProcessLookupError):
                pass


def test_stop_all_is_absent_from_real_mcp_and_capability_dispatch(daemon):
    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "omnimcp", "--profile", "compact"],
            env=daemon.env,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names == {"discover", "observe", "act", "workflow", "job", "events", "artifact"}
            for name, args in (
                ("act", {"action": "worker_stop_all"}),
                ("workflow", {"steps": [{"id": "stop", "action": "worker_stop_all"}]}),
            ):
                result = await client.call_tool(name, args)
                assert json.loads(result.content[0].text)["status"] == "unsupported"
    asyncio.run(asyncio.wait_for(run(), timeout=15))
