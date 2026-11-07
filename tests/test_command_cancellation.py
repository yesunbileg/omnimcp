import contextlib
import os
import signal
import subprocess
import sys
import threading
import time

import psutil

from omnimcp.core.execution import Context
from omnimcp.core.state import Store


def test_cancel_kills_term_resistant_child_after_leader_exits(tmp_path):
    store = Store(tmp_path / "state")
    job = store.create_job("probe")
    store.update_job(job, "running")
    ctx = Context(store, job_id=job)
    marker = tmp_path / "child"
    child_code = (
        "import os,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        'open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(60)'
    )
    leader_code = (
        "import subprocess,sys,time; "
        'subprocess.Popen([sys.executable,"-c",sys.argv[2],sys.argv[1]]); time.sleep(60)'
    )
    result = {}
    thread = threading.Thread(
        target=lambda: result.update(
            ctx.run([sys.executable, "-c", leader_code, str(marker), child_code])
        )
    )
    thread.start()
    pid = birth = None
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        pid = int(marker.read_text())
        birth = psutil.Process(pid).create_time()
        ctx.cancelled.set()
        thread.join(8)
        assert not thread.is_alive()
        assert result["status"] == "cancelled"
        try:
            proc = psutil.Process(pid)
            assert proc.create_time() != birth or proc.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
    finally:
        if pid is not None:
            try:
                proc = psutil.Process(pid)
                if proc.create_time() == birth and proc.status() != psutil.STATUS_ZOMBIE:
                    os.kill(pid, signal.SIGKILL)
            except (psutil.Error, ProcessLookupError):
                pass
        ctx.cancelled.set()
        thread.join(8)
        store.close()


def test_stop_process_group_confirms_kill_before_reporting_stopped(tmp_path):
    store = Store(tmp_path / "state")
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
        ],
        start_new_session=True,
    )
    try:
        birth = psutil.Process(child.pid).create_time()
        result = store.stop_process_group(child.pid, child.pid, birth)
        assert result["status"] == "stopped"
        try:
            proc = psutil.Process(child.pid)
            assert proc.create_time() != birth or proc.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        store.close()


def test_stop_process_group_does_not_report_stopped_before_kill_is_observed(tmp_path, monkeypatch):
    store = Store(tmp_path / "state")
    marker = tmp_path / "ready"
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "open(sys.argv[1], 'w').close(); time.sleep(60)",
            str(marker),
        ],
        start_new_session=True,
    )
    kill = os.kill

    def delayed_kill(pid, sig):
        if sig != signal.SIGKILL:
            return kill(pid, sig)

    monkeypatch.setattr(os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(os, "kill", delayed_kill)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        birth = psutil.Process(child.pid).create_time()
        result = store.stop_process_group(child.pid, child.pid, birth)
        assert result["status"] == "termination_pending"
        assert child.poll() is None
        assert result["killed"] == 0
    finally:
        monkeypatch.setattr(os, "kill", kill)
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        store.close()


def test_exited_group_leader_with_live_member_remains_pending(tmp_path, monkeypatch):
    store = Store(tmp_path / "state")
    marker = tmp_path / "child"
    child_code = (
        "import os,signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)"
    )
    leader_code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]]); "
        "time.sleep(.1)"
    )
    leader = subprocess.Popen(
        [sys.executable, "-c", leader_code, str(marker), child_code], start_new_session=True
    )
    birth = psutil.Process(leader.pid).create_time()
    try:
        assert leader.wait(timeout=3) == 0
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        child_pid = int(marker.read_text())
        killpg_calls = []
        monkeypatch.setattr(os, "killpg", lambda *args: killpg_calls.append(args))
        result = store.stop_process_group(leader.pid, leader.pid, birth)
        assert result["status"] == "termination_pending"
        assert result["killed"] == 0
        assert killpg_calls == []
        assert psutil.Process(child_pid).status() != psutil.STATUS_ZOMBIE
    finally:
        if marker.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(marker.read_text()), signal.SIGKILL)
        store.close()
