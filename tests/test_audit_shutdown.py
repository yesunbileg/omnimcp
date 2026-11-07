"""Shutdown regressions that must run in isolated worker processes."""

import json
import os
import socket
import subprocess
import sys
import time

import psutil

from omnimcp.core.state import Store


def _rpc(path, request):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        client.connect(str(path))
        client.sendall(json.dumps(request).encode() + b"\n")
        return json.loads(client.makefile("rb").readline())


def test_worker_shutdown_is_bounded_and_does_not_orphan_recorded_children(tmp_path):
    state = tmp_path / "state"
    sock = tmp_path / "worker.sock"
    ready = tmp_path / "child-ready"
    env = {
        **os.environ,
        "OMNIMCP_STATE_DIR": str(state),
        "OMNIMCP_SOCKET": str(sock),
        "OMNIMCP_PROFILE": "compact",
    }
    runner = r"""
import asyncio, os, subprocess, sys, threading
import psutil
from omnimcp.core import worker
from omnimcp.core.registry import Registry

def registry():
    result = Registry()
    def blocked(ctx):
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(60)",
            ],
            start_new_session=True,
        )
        ctx.store.track_process(
            ctx.job_id, child.pid, child.pid, psutil.Process(child.pid).create_time()
        )
        with open(sys.argv[1], "w") as marker:
            marker.write(str(child.pid))
        threading.Event().wait(60)
    result.add("blocked", blocked)
    return result

worker.build_registry = registry
asyncio.run(worker.serve())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", runner, str(ready)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child_pid = None
    job_id = None
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not sock.exists():
            if process.poll() is not None:
                out, err = process.communicate()
                raise AssertionError((out.decode(), err.decode()))
            time.sleep(0.02)
        assert sock.exists(), "worker failed to create its socket"
        submitted = _rpc(sock, {"op": "act", "action": "blocked", "params": {}})
        assert submitted["status"] == "queued"
        job_id = submitted["job_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not ready.exists():
            time.sleep(0.02)
        assert ready.exists(), "blocked handler did not start"
        child_pid = int(ready.read_text())

        started = time.monotonic()
        process.terminate()
        process.wait(timeout=9)
        assert time.monotonic() - started < 9
        try:
            child = psutil.Process(child_pid)
            assert child.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
        store = Store(state)
        try:
            assert store.job(job_id)["status"] == "interrupted"
            assert any(
                event["status"] == "shutdown_pending"
                for event in store.events(kind="worker")["items"]
            )
        finally:
            store.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        if child_pid:
            try:
                child = psutil.Process(child_pid)
                if child.status() != psutil.STATUS_ZOMBIE:
                    child.kill()
            except psutil.NoSuchProcess:
                pass
