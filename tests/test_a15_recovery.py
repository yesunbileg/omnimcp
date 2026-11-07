"""Recovery must only kill verified members of a saved process group."""

import os
import signal
import subprocess
import sys
import time

import psutil
import pytest

from omnimcp.core.state import Store


def alive(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_orphaned_member_is_killed(tmp_path):
    child_file = tmp_path / "child"
    code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',"
        "'import os,signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        'open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(40)\',sys.argv[1]]); '
        "time.sleep(40)"
    )
    leader = subprocess.Popen([sys.executable, "-c", code, str(child_file)], start_new_session=True)
    child = None
    birth = None
    try:
        deadline = time.monotonic() + 5
        while not child_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_file.exists()
        child = int(child_file.read_text())
        birth = psutil.Process(child).create_time()
        store = Store(tmp_path / "state")
        try:
            job = store.create_job("test")
            store.track_process(
                job, leader.pid, leader.pid, psutil.Process(leader.pid).create_time()
            )
            store.recover_processes()
            deadline = time.monotonic() + 2
            while alive(child) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not alive(child)
        finally:
            store.close()
    finally:
        if child is not None:
            try:
                p = psutil.Process(child)
                if p.create_time() == birth and alive(child):
                    os.kill(child, signal.SIGKILL)
            except psutil.NoSuchProcess:
                pass
        if leader.poll() is None:
            leader.kill()
        leader.wait(timeout=5)


@pytest.mark.parametrize("gone", [False, True])
def test_unverified_leader_never_signals(tmp_path, monkeypatch, gone):
    leader = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    birth = psutil.Process(leader.pid).create_time()
    store = Store(tmp_path / "state")
    try:
        job = store.create_job("test")
        store.track_process(job, leader.pid, leader.pid, birth if gone else birth - 100)
        if gone:
            leader.terminate()
            leader.wait(timeout=5)
        calls = []
        monkeypatch.setattr(os, "killpg", lambda *args: calls.append(args))
        monkeypatch.setattr(os, "kill", lambda *args: calls.append(args))
        store.recover_processes()
        assert calls == []
        if gone:
            events = store.events(kind="process")["items"]
            assert any(
                e.get("message") == "group leader gone; members not verified" for e in events
            )
    finally:
        monkeypatch.undo()
        store.close()
        if leader.poll() is None:
            leader.terminate()
        leader.wait(timeout=5)
