import threading
import time

import pytest

from omnimcp.core.engine import Engine
from omnimcp.core.registry import Fault, Registry
from omnimcp.core.state import Store


def test_stop_all_cancels_queued_jobs_without_waiting_for_blocked_threads(tmp_path):
    store = Store(tmp_path)
    engine = Engine(Registry(), store)
    release = threading.Event()
    started = threading.Barrier(5)

    def blocked(ctx):
        started.wait()
        release.wait(15)
        return {"status": "ok"}

    jobs = [engine.submit("blocked", blocked)["job_id"] for _ in range(4)]
    try:
        started.wait(timeout=5)
        queued = engine.submit("queued", lambda ctx: {"status": "ok"})["job_id"]
        start = time.monotonic()
        result = engine.stop_all()
        assert time.monotonic() - start < 10
        assert result["cancelled"] == 5
        assert result["threads_still_busy"] == 4
        assert result["groups_terminated"] == 0
        assert result["killed"] == 0
        assert all(store.job(job)["status"] == "cancelled" for job in [*jobs, queued])
        repeated = engine.stop_all()
        assert repeated["cancelled"] == 0
        assert repeated["threads_still_busy"] == 4
    finally:
        release.set()
        engine.close()
        store.close()


def test_cancelled_job_cannot_be_reopened_by_late_progress(tmp_path):
    store = Store(tmp_path)
    try:
        job = store.create_job("test")
        store.update_job(job, "cancelled")
        store.update_job(job, "running", progress={"late": True})
        assert store.job(job)["status"] == "cancelled"
    finally:
        store.close()


def test_stop_all_terminates_recorded_process_even_when_handler_is_blocked(tmp_path):
    import os
    import signal
    import subprocess
    import sys

    import psutil

    store = Store(tmp_path / "state")
    engine = Engine(Registry(), store)
    release = threading.Event()
    ready = threading.Event()
    marker = tmp_path / "ready"
    process = None

    def blocked(ctx):
        nonlocal process
        code = (
            "import signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            'open(sys.argv[1],"w").write("ready"); time.sleep(60)'
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(marker)], start_new_session=True
        )
        store.track_process(
            ctx.job_id, process.pid, process.pid, psutil.Process(process.pid).create_time()
        )
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        ready.set()
        release.wait(15)
        return {"status": "ok"}

    job = engine.submit("blocked", blocked)["job_id"]
    try:
        assert ready.wait(5)
        assert marker.exists()
        result = engine.stop_all()
        assert result["groups_terminated"] == 1
        assert result["killed"] == 1
        assert result["threads_still_busy"] == 1
        process.wait(timeout=2)
        assert store.job(job)["status"] == "cancelled"
        assert engine.stop_all()["groups_terminated"] == 0
    finally:
        if process and process.poll() is None:
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        release.set()
        engine.close()
        store.close()


def test_cancelled_tracked_job_is_retried_on_recovery(tmp_path, monkeypatch):
    store = Store(tmp_path)
    job = store.create_job("test")
    store.track_process(job, 1234, 1234, 1.0)
    store.update_job(job, "cancelled")
    called = []
    monkeypatch.setattr(
        store,
        "stop_process_group",
        lambda *identity: called.append(identity) or {"status": "termination_denied", "killed": 0},
    )
    try:
        store.recover_processes()
        assert called == [(1234, 1234, 1.0)]
        assert store.job(job)["pid"] == 1234
    finally:
        store.close()


def test_interrupted_tracked_job_is_retried_on_recovery(tmp_path, monkeypatch):
    store = Store(tmp_path)
    job = store.create_job("test")
    store.track_process(job, 1234, 1234, 1.0)
    store.update_job(job, "interrupted")
    called = []
    monkeypatch.setattr(
        store,
        "stop_process_group",
        lambda *identity: called.append(identity) or {"status": "termination_pending", "killed": 0},
    )
    try:
        store.recover_processes()
        assert called == [(1234, 1234, 1.0)]
        assert store.job(job)["pid"] == 1234
    finally:
        store.close()


def test_close_deadline_includes_store_lock_wait(tmp_path):
    store = Store(tmp_path)
    engine = Engine(Registry(), store)
    store.lock.acquire()
    try:
        started = time.monotonic()
        result = engine.close(timeout=0.15)
        assert time.monotonic() - started < 0.5
        assert result["status"] == "shutdown_pending"
        assert result["store_safe_to_close"] is False
    finally:
        store.lock.release()
        engine.close(timeout=2)
        store.close()


def test_process_records_are_unique_and_old_untrack_preserves_new_identity(tmp_path):
    store = Store(tmp_path)
    job = store.create_job("test")
    first = store.track_process(job, 1111, 1111, 1.0)
    second = store.track_process(job, 2222, 2222, 2.0)
    foreground = store.track_process("", 3333, 3333, 3.0)
    try:
        assert first.startswith("p") and second.startswith("p") and foreground.startswith("p")
        assert len({first, second, foreground}) == 3
        store.untrack_process(first)
        with store.lock:
            rows = store.db.execute(
                "SELECT id,pid,pgid,create_time FROM processes ORDER BY id"
            ).fetchall()
            job_identity = store.db.execute(
                "SELECT pid,pgid,create_time FROM jobs WHERE id=?", (job,)
            ).fetchone()
        assert {(row[0], row[1], row[2], row[3]) for row in rows} == {
            (second, 2222, 2222, 2.0),
            (foreground, 3333, 3333, 3.0),
        }
        assert tuple(job_identity) == (2222, 2222, 2.0)
    finally:
        store.close()


def test_pending_process_result_is_retried_on_later_stop(tmp_path, monkeypatch):
    store = Store(tmp_path)
    outcomes = iter(
        [
            {"status": "termination_pending", "killed": 0},
            {"status": "stopped", "killed": 1},
        ]
    )
    calls = []
    monkeypatch.setattr(
        store,
        "_stop_process_group",
        lambda *identity: calls.append(identity) or next(outcomes),
    )
    try:
        assert store.stop_process_group(1111, 1111, 1.0)["status"] == "termination_pending"
        assert store.stop_process_group(1111, 1111, 1.0)["status"] == "stopped"
        assert calls == [(1111, 1111, 1.0), (1111, 1111, 1.0)]
    finally:
        store.close()


def test_close_deadline_includes_blocking_close_hook(tmp_path):
    store = Store(tmp_path)
    engine = Engine(Registry(), store)
    release = threading.Event()
    engine.registry.close_hooks = [lambda: release.wait()]
    try:
        started = time.monotonic()
        result = engine.close(timeout=0.15)
        assert time.monotonic() - started < 0.5
        assert result["status"] == "shutdown_pending"
        assert result["store_safe_to_close"] is False
    finally:
        release.set()
        assert engine.close(timeout=2)["store_safe_to_close"]
        store.close()


def test_request_registration_keeps_store_open_and_submit_rejects_after_close(tmp_path):
    store = Store(tmp_path)
    engine = Engine(Registry(), store)
    entered = threading.Event()
    release = threading.Event()
    engine._request = lambda request: entered.set() or release.wait() or {"status": "ok"}
    request_thread = threading.Thread(target=lambda: engine.request({"op": "discover"}))
    request_thread.start()
    try:
        assert entered.wait(2)
        result = engine.close(timeout=0.1)
        assert result["store_safe_to_close"] is False
        with pytest.raises(Fault, match="stopping"):
            engine.submit("late", lambda ctx: {"status": "ok"})
    finally:
        release.set()
        request_thread.join(2)
        engine.close(timeout=2)
        store.close()
