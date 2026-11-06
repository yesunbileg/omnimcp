import threading
import time

from omnimcp.core.engine import Engine
from omnimcp.core.registry import Registry
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
