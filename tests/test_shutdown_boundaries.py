"""Shutdown ordering, complete lifetime tracking and durable process ownership."""

import os
import socket
import subprocess
import sys
import threading
import time

import pytest

from omnimcp.core.engine import Engine
from omnimcp.core.registry import Fault, Registry
from omnimcp.core.state import Store


def test_close_cancels_foreground_before_waiting_for_request(tmp_path):
    store = Store(tmp_path / "state")
    registry = Registry()
    entered = threading.Event()
    outcome = {}

    def wait_for_cancel(ctx):
        entered.set()
        assert ctx.cancelled.wait(1), "shutdown waited for the request before cancelling it"
        return {"status": "cancelled"}

    registry.add("wait", wait_for_cancel)
    engine = Engine(registry, store)
    request = threading.Thread(
        target=lambda: outcome.update(
            engine.request({"op": "act", "action": "wait", "background": False})
        )
    )
    request.start()
    try:
        assert entered.wait(1)
        result = engine.close(timeout=0.3)
        assert result["store_safe_to_close"] is True
        assert outcome["status"] == "cancelled"
    finally:
        request.join(2)
        if engine.close(timeout=2)["store_safe_to_close"]:
            store.close()


def test_close_waits_for_entire_read_request_and_can_complete_after_timeout(tmp_path):
    store = Store(tmp_path / "state")
    registry = Registry()
    entered, release = threading.Event(), threading.Event()

    def read(ctx):
        entered.set()
        release.wait(2)
        return {"value": 1}

    registry.add("read", read, readonly=True)
    engine = Engine(registry, store)
    reader = threading.Thread(target=lambda: engine.request({"op": "observe", "action": "read"}))
    reader.start()
    try:
        assert entered.wait(1)
        assert engine.close(timeout=0.02)["store_safe_to_close"] is False
        with pytest.raises(Fault, match="stopping"):
            engine.submit("late", lambda ctx: {"status": "ok"})
        release.set()
        reader.join(1)
        assert engine.close(timeout=1)["store_safe_to_close"] is True
    finally:
        release.set()
        reader.join(2)
        if engine.close(timeout=2)["store_safe_to_close"]:
            store.close()


def test_foreground_pending_process_record_survives_restart(tmp_path, monkeypatch):
    store = Store(tmp_path / "state")
    first = store.track_process("", 12345, 12345, 1.0)
    assert first.startswith("p")
    store.close()
    reopened = Store(tmp_path / "state")
    calls = []
    monkeypatch.setattr(
        reopened,
        "stop_process_group",
        lambda *identity: calls.append(identity) or {"status": "termination_pending", "killed": 0},
    )
    reopened.recover_processes()
    assert calls == [(12345, 12345, 1.0)]
    assert reopened.db.execute("SELECT id FROM processes").fetchone()[0] == first
    reopened.close()


def test_finishing_old_command_cannot_clear_newer_process_on_same_job(tmp_path):
    store = Store(tmp_path / "state")
    job = store.create_job("commands")
    first = store.track_process(job, 12345, 12345, 1.0)
    second = store.track_process(job, 12346, 12346, 2.0)
    assert first != second
    store.untrack_process(first)
    assert store.job(job)["pid"] == 12346
    assert store.db.execute("SELECT id FROM processes").fetchone()[0] == second
    store.close()


def test_pending_process_on_failed_job_is_recovered(tmp_path, monkeypatch):
    store = Store(tmp_path / "state")
    job = store.create_job("failed-pending")
    ref = store.track_process(job, 12345, 12345, 1.0)
    store.update_job(job, "failed", {"status": "timeout_pending"})
    calls = []
    monkeypatch.setattr(
        store,
        "stop_process_group",
        lambda *args: calls.append(args) or {"status": "termination_pending", "killed": 0},
    )
    store.recover_processes()
    assert calls == [(12345, 12345, 1.0)]
    assert store.db.execute("SELECT id FROM processes").fetchone()[0] == ref
    store.close()


@pytest.mark.parametrize("mode", ["store-lock", "engine-lock", "hook"])
def test_worker_shutdown_deadline_includes_locks_and_hooks(tmp_path, mode):
    marker = tmp_path / "ready"
    sock = tmp_path / "worker.sock"
    runner = r"""
import asyncio, sys, threading
from pathlib import Path
from omnimcp.core import worker
from omnimcp.core.engine import Engine
from omnimcp.core.registry import Registry
mode, marker = sys.argv[1:]
original_close = Engine.close
def short_close(self):
    return original_close(self, timeout=.2)
Engine.close = short_close
def build_registry():
    r = Registry()
    def blocked(ctx):
        lock = ctx.store.lock if mode == 'store-lock' else ctx.engine.lock
        with lock:
            Path(marker).touch()
            threading.Event().wait(60)
    r.add('blocked', blocked)
    if mode == 'hook':
        def blocked_hook():
            threading.Event().wait(60)
        r.close_hooks = [blocked_hook]
    return r
worker.build_registry = build_registry
asyncio.run(worker.serve())
"""
    env = {**os.environ, "OMNIMCP_STATE_DIR": str(tmp_path / "state"), "OMNIMCP_SOCKET": str(sock)}
    process = subprocess.Popen(
        [sys.executable, "-c", runner, mode, str(marker)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not sock.exists():
            assert process.poll() is None, process.communicate()
            time.sleep(0.01)
        assert sock.exists()
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(sock))
            if mode == "hook":
                client.sendall(b'{"op":"discover"}\n')
                assert client.recv(65536)
            else:
                client.sendall(b'{"op":"act","action":"blocked"}\n')
                while time.monotonic() < deadline and not marker.exists():
                    time.sleep(0.01)
                assert marker.exists()
        started = time.monotonic()
        process.terminate()
        process.wait(timeout=2)
        assert time.monotonic() - started < 2
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=2)


def test_unreadable_group_identity_is_pending_denial_not_an_exception(tmp_path, monkeypatch):
    import psutil

    store = Store(tmp_path / "state")

    def denied(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(psutil, "Process", denied)
    try:
        result = store.stop_process_group(12345, 12345, 1.0)
        assert result["status"] == "termination_denied"
        assert result["killed"] == 0
    finally:
        store.close()
