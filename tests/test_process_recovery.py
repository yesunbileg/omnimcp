"""Interrupted worker process groups are recovered by durable process identity."""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from omnimcp.core.client import rpc
from omnimcp.core.state import Store

SRC = Path(__file__).resolve().parents[1] / "src"


class IsolatedWorker:
    def __init__(self, root):
        self.root = root
        self.env = {
            **os.environ,
            "OMNIMCP_STATE_DIR": str(root / "state"),
            "OMNIMCP_SOCKET": str(root / "worker.sock"),
            "OMNIMCP_PROFILE": "compact",
            "PYTHONPATH": str(SRC),
        }
        self.proc = None
        self.processes = []

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "omnimcp.core.worker"],
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                pytest.fail(self.proc.communicate()[1].decode())
            if Path(self.env["OMNIMCP_SOCKET"]).exists():
                response = rpc({"op": "discover", "limit": 1})
                if response.get("status") != "worker_unavailable":
                    return
            time.sleep(0.02)
        pytest.fail("worker startup timed out")

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL)
            self.proc.wait(timeout=5)
        if self.proc:
            self.proc.communicate()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        if self.proc:
            _, err = self.proc.communicate()
            assert b"Traceback" not in err


@pytest.fixture
def worker(tmp_path, monkeypatch):
    value = IsolatedWorker(tmp_path)
    monkeypatch.setenv("OMNIMCP_SOCKET", value.env["OMNIMCP_SOCKET"])
    value.start()
    yield value
    value.stop()
    for pid, pgid, birth, child_pid in value.processes:
        try:
            process = psutil.Process(pid)
            if (process.create_time() == birth and os.getpgid(pid) == pgid
                    and process.status() != psutil.STATUS_ZOMBIE):
                os.killpg(pgid, signal.SIGTERM)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and (_active(pid) or _active(child_pid)):
                    time.sleep(0.05)
                if _active(pid):
                    process = psutil.Process(pid)
                    if process.create_time() == birth and os.getpgid(pid) == pgid:
                        os.kill(pid, signal.SIGKILL)
        except (psutil.Error, ProcessLookupError, PermissionError):
            continue


def _running_command(worker, tmp_path):
    pid_file = tmp_path / "child.pid"
    code = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen(['/bin/sleep','60']); "
        "open(sys.argv[1],'w').write(str(p.pid)); time.sleep(60)"
    )
    response = rpc({
        "op": "act",
        "action": "command.exec",
        "params": {"argv": [sys.executable, "-c", code, str(pid_file)]},
    })
    assert response["status"] == "queued", response
    job_id = response["job_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not pid_file.exists():
        time.sleep(0.02)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    db = Path(worker.env["OMNIMCP_STATE_DIR"]) / "state.sqlite3"
    while time.monotonic() < deadline:
        with sqlite3.connect(db) as connection:
            row = connection.execute(
                "SELECT pid,pgid,create_time FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        if row and row[0]:
            break
        time.sleep(0.02)
    assert row and row[0] == row[1] and row[2] > 0
    worker.processes.append((row[0], row[1], row[2], child_pid))
    return job_id, child_pid, row


def _active(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _wait_inactive(pid, timeout=7):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _active(pid):
            return True
        time.sleep(0.05)
    return not _active(pid)


def test_sigkill_restart_stops_orphan_job_process_group(worker, tmp_path):
    job_id, child_pid, (pid, pgid, birth) = _running_command(worker, tmp_path)
    assert _active(child_pid)
    worker.kill()
    worker.start()
    assert _wait_inactive(pid)
    assert _wait_inactive(child_pid)
    result = rpc({"op": "job", "job_id": job_id})
    assert result["status"] == "interrupted"
    db = Path(worker.env["OMNIMCP_STATE_DIR"]) / "state.sqlite3"
    with sqlite3.connect(db) as connection:
        saved = connection.execute(
            "SELECT pid,pgid,create_time FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert saved == (None, None, None)
    events = rpc({"op": "events", "since": 0, "kind": "process"})["items"]
    assert any(e.get("pid") == pid and e.get("pgid") == pgid for e in events)


def test_sigkill_restart_skips_pid_when_saved_creation_time_differs(worker, tmp_path):
    job_id, child_pid, (pid, pgid, birth) = _running_command(worker, tmp_path)
    db = Path(worker.env["OMNIMCP_STATE_DIR"]) / "state.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE jobs SET create_time=? WHERE id=?", (birth - 10, job_id))
    worker.kill()
    worker.start()
    assert _active(pid) and _active(child_pid)
    assert rpc({"op": "job", "job_id": job_id})["status"] == "interrupted"
    events = rpc({"op": "events", "since": 0, "kind": "process"})["items"]
    assert any(e.get("pid") == pid and e["status"] == "pid_reused" for e in events)


def test_base_database_job_and_artifact_survive_additive_migration(tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    artifact = root / "saved-output"
    artifact.write_text("legacy artifact bytes\n")
    ids = {"job": "jlegacy", "artifact": "alegacy"}
    with sqlite3.connect(root / "state.sqlite3") as db:
        db.executescript("""
            CREATE TABLE jobs (id TEXT PRIMARY KEY, action TEXT, status TEXT, created REAL,
                updated REAL, result TEXT, progress TEXT);
            CREATE TABLE artifacts (id TEXT PRIMARY KEY, path TEXT, kind TEXT, created REAL);
        """)
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",
            (ids["job"], "command.exec", "succeeded", 0, 0,
             json.dumps({"output": ids["artifact"]}), None),
        )
        db.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?)", (ids["artifact"], str(artifact), "text", 0)
        )

    store = Store(root)
    try:
        job = store.job(ids["job"])
        assert job["action"] == "command.exec" and job["status"] == "succeeded"
        assert store.read(ids["artifact"])["data"] == "legacy artifact bytes\n"
        columns = {row[1] for row in store.db.execute("PRAGMA table_info(jobs)")}
        assert {"pid", "pgid", "create_time"} <= columns
    finally:
        store.close()
