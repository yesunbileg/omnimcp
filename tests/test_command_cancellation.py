import os
import signal
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
