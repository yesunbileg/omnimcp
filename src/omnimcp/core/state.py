"""Private SQLite state and immutable artifacts. No command arguments in events."""

from __future__ import annotations

import base64
import json
import os
import signal
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import psutil

from .registry import Fault

BUDGET = 16 * 1024
TERM_GRACE = 0.5
KILL_VERIFY_GRACE = 1.0


def state_dir() -> Path:
    return Path(
        os.environ.get("OMNIMCP_STATE_DIR")
        or Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omnimcp"
    )


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:16]


class Store:
    def __init__(self, root: Path | None = None):
        self.root = root or state_dir()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir(mode=0o700, exist_ok=True)
        self.lock = threading.RLock()
        self.process_locks = {}
        self.process_results = {}
        self.db = sqlite3.connect(self.root / "state.sqlite3", check_same_thread=False)
        os.chmod(self.root / "state.sqlite3", 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, action TEXT, status TEXT, created REAL,
                updated REAL, result TEXT, progress TEXT, pid INTEGER, pgid INTEGER,
                create_time REAL);
            CREATE TABLE IF NOT EXISTS events (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY, path TEXT, kind TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS auth_blocks (key TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE IF NOT EXISTS processes (
                id TEXT PRIMARY KEY, job_id TEXT, pid INTEGER, pgid INTEGER,
                create_time REAL, updated REAL);
        """)
        for name, kind in (("pid", "INTEGER"), ("pgid", "INTEGER"), ("create_time", "REAL")):
            try:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        self.db.commit()
        rows = self.db.execute(
            "SELECT id,pid,pgid,create_time FROM jobs WHERE pid IS NOT NULL"
        ).fetchall()
        for job_id, pid, pgid, birth in rows:
            exists = self.db.execute(
                "SELECT 1 FROM processes WHERE job_id=? AND pid=? AND pgid=? AND create_time=?",
                (job_id, pid, pgid, birth),
            ).fetchone()
            if not exists:
                self.db.execute(
                    "INSERT INTO processes VALUES(?,?,?,?,?,?)",
                    (new_id("p"), job_id, pid, pgid, birth, time.time()),
                )
        self.db.commit()

    def close(self):
        self.db.close()

    def event(self, kind: str, data: dict):
        with self.lock:
            self.db.execute(
                "INSERT INTO events(ts,kind,data) VALUES(?,?,?)", (time.time(), kind, encode(data))
            )
            self.db.commit()

    def events(self, since: int = 0, limit: int = 50, kind: str = "") -> dict:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM events WHERE cursor>? AND (?='' OR kind=?) ORDER BY cursor LIMIT ?",
                (since, kind, kind, limit + 1),
            ).fetchall()
        items = [
            {"cursor": r["cursor"], "time": r["ts"], "kind": r["kind"], **json.loads(r["data"])}
            for r in rows[:limit]
        ]
        return {
            "items": items,
            "cursor": items[-1]["cursor"] if items else since,
            "more": len(rows) > limit,
        }

    def create_job(self, action: str) -> str:
        ref = new_id("j")
        with self.lock:
            self.db.execute(
                "INSERT INTO jobs(id,action,status,created,updated,result,progress) "
                "VALUES(?,?,?,?,?,?,?)",
                (ref, action, "queued", time.time(), time.time(), None, None),
            )
            self.db.commit()
        self.event("job", {"job_id": ref, "status": "queued", "action": action})
        return ref

    def update_job(self, ref: str, status: str, result=None, progress=None):
        with self.lock:
            cursor = self.db.execute(
                "UPDATE jobs SET status=?, updated=?, result=COALESCE(?,result), "
                "progress=COALESCE(?,progress) WHERE id=? "
                "AND status NOT IN ('cancelled','interrupted')",
                (
                    status,
                    time.time(),
                    encode(result) if result is not None else None,
                    encode(progress) if progress is not None else None,
                    ref,
                ),
            )
            self.db.commit()
        if cursor.rowcount:
            self.event("job", {"job_id": ref, "status": status})

    def job(self, ref: str = "", offset: int = 0, limit: int = 30):
        with self.lock:
            if ref:
                row = self.db.execute("SELECT * FROM jobs WHERE id=?", (ref,)).fetchone()
                if not row:
                    raise Fault("not_found", "Unknown job.")
                rows = [row]
            else:
                rows = self.db.execute(
                    "SELECT * FROM jobs ORDER BY created DESC LIMIT ? OFFSET ?", (limit, offset)
                ).fetchall()
        out = [
            {
                **dict(r),
                "result": json.loads(r["result"]) if r["result"] else None,
                "progress": json.loads(r["progress"]) if r["progress"] else None,
            }
            for r in rows
        ]
        return (
            out[0] if ref else {"items": out, "next": offset + limit if len(out) == limit else None}
        )

    def recover(self):
        with self.lock:
            rows = self.db.execute(
                "SELECT id FROM jobs WHERE status IN ('queued','running')"
            ).fetchall()
            for row in rows:
                self.update_job(
                    row["id"],
                    "interrupted",
                    {"status": "interrupted", "message": "Worker stopped; not replayed."},
                )

    def track_process(self, job_id: str, pid: int, pgid: int, create_time: float):
        """Persist a process identity independently of the lifetime of its job."""
        record_id = new_id("p")
        with self.lock:
            if job_id:
                self.db.execute(
                    "UPDATE jobs SET pid=?,pgid=?,create_time=? WHERE id=?",
                    (pid, pgid, create_time, job_id),
                )
            self.db.execute(
                "INSERT INTO processes VALUES(?,?,?,?,?,?)",
                (record_id, job_id or None, pid, pgid, create_time, time.time()),
            )
            self.db.commit()
        return record_id

    def untrack_process(self, record_id: str):
        if not record_id:
            return
        with self.lock:
            row = self.db.execute(
                "SELECT id,job_id,pid,pgid,create_time FROM processes WHERE id=?", (record_id,)
            ).fetchone()
            if row is None:
                # Keep compatibility with older callers that supplied a job ID.
                row = self.db.execute(
                    "SELECT id,job_id,pid,pgid,create_time FROM processes "
                    "WHERE job_id=? ORDER BY updated DESC LIMIT 1",
                    (record_id,),
                ).fetchone()
                if row is None:
                    return
            self.db.execute("DELETE FROM processes WHERE id=?", (row["id"],))
            if row["job_id"]:
                self.db.execute(
                    "UPDATE jobs SET pid=NULL,pgid=NULL,create_time=NULL WHERE id=? "
                    "AND pid=? AND pgid=? AND create_time=? "
                    "AND NOT EXISTS (SELECT 1 FROM processes WHERE job_id=? "
                    "AND pid=? AND pgid=? AND create_time=?)",
                    (
                        row["job_id"],
                        row["pid"],
                        row["pgid"],
                        row["create_time"],
                        row["job_id"],
                        row["pid"],
                        row["pgid"],
                        row["create_time"],
                    ),
                )
            self.db.commit()

    def stop_process_group(self, pid: int, pgid: int, birth: float) -> dict:
        """Terminate a verified group and individually kill its surviving snapshot."""
        identity = (pid, pgid, birth)
        with self.lock:
            lock = self.process_locks.setdefault(identity, threading.Lock())
        with lock:
            if identity not in self.process_results:
                result = self._stop_process_group(pid, pgid, birth)
                if result["status"] not in {"termination_denied", "termination_pending"}:
                    self.process_results[identity] = result
                return result
            return self.process_results[identity]

    def _stop_process_group(self, pid: int, pgid: int, birth: float) -> dict:
        result = {"status": "unsafe_identity", "killed": 0}
        if pid <= 1 or pgid <= 1 or pid != pgid or pid == os.getpid() or pgid == os.getpgrp():
            return result
        try:
            leader = psutil.Process(pid)
            if leader.status() == psutil.STATUS_ZOMBIE:
                result["status"] = "termination_pending"
                result["message"] = "Group leader is a zombie; members are unverified."
                return result
        except psutil.NoSuchProcess:
            result["status"] = "termination_pending"
            result["message"] = "group leader gone; members not verified"
            return result
        except (psutil.AccessDenied, PermissionError, OSError):
            result["status"] = "termination_denied"
            return result
        try:
            if leader.create_time() != birth or os.getpgid(pid) != pgid:
                result["status"] = "pid_reused"
                return result
            members = []
            for process in psutil.process_iter():
                try:
                    if os.getpgid(process.pid) == pgid:
                        members.append((process.pid, process.create_time()))
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    ProcessLookupError,
                    PermissionError,
                ):
                    continue
            # Revalidate after the snapshot, immediately before the group signal.
            leader = psutil.Process(pid)
            if (
                leader.create_time() != birth
                or os.getpgid(pid) != pgid
                or leader.status() == psutil.STATUS_ZOMBIE
            ):
                result["status"] = "pid_reused"
                return result
            os.killpg(pgid, signal.SIGTERM)
            result["status"] = "stopped"
            deadline = time.monotonic() + TERM_GRACE
            remaining = list(members)
            while time.monotonic() < deadline:
                remaining = []
                for member_pid, member_birth in members:
                    try:
                        member = psutil.Process(member_pid)
                        if (
                            member.create_time() == member_birth
                            and member.status() != psutil.STATUS_ZOMBIE
                        ):
                            remaining.append((member_pid, member_birth))
                    except psutil.NoSuchProcess:
                        pass
                    except (psutil.AccessDenied, PermissionError, OSError):
                        result["status"] = "termination_denied"
                if not remaining:
                    break
                time.sleep(0.05)
            kill_targets = []
            for member_pid, member_birth in remaining:
                try:
                    member = psutil.Process(member_pid)
                    if (
                        member.create_time() == member_birth
                        and member.status() != psutil.STATUS_ZOMBIE
                    ):
                        os.kill(member_pid, signal.SIGKILL)
                        kill_targets.append((member_pid, member_birth))
                except (psutil.NoSuchProcess, ProcessLookupError):
                    pass
                except (psutil.AccessDenied, PermissionError, OSError):
                    result["status"] = "termination_denied"
            verify_deadline = time.monotonic() + KILL_VERIFY_GRACE
            alive = list(members)
            while time.monotonic() < verify_deadline:
                alive = []
                for member_pid, member_birth in members:
                    try:
                        member = psutil.Process(member_pid)
                        if (
                            member.create_time() == member_birth
                            and member.status() != psutil.STATUS_ZOMBIE
                        ):
                            alive.append((member_pid, member_birth))
                    except psutil.NoSuchProcess:
                        pass
                    except (psutil.AccessDenied, PermissionError, OSError):
                        result["status"] = "termination_denied"
                if result["status"] == "termination_denied" or not alive:
                    break
                time.sleep(0.05)
            if result["status"] != "termination_denied" and alive:
                result["status"] = "termination_pending"
                result["message"] = "Verified process group members remain after SIGKILL."
            alive_ids = set(alive)
            result["killed"] = sum(target not in alive_ids for target in kill_targets)
        except (psutil.NoSuchProcess, ProcessLookupError):
            result["status"] = "termination_pending"
            result["message"] = "Group leader identity changed or vanished; members unverified."
        except (psutil.AccessDenied, PermissionError, OSError):
            result["status"] = "termination_denied"
        return result

    def recover_processes(self):
        """Stop only saved process groups whose leader identity still matches."""
        if self.root.stat().st_uid != os.getuid():
            return
        with self.lock:
            rows = self.db.execute(
                "SELECT id,job_id,pid,pgid,create_time FROM processes"
            ).fetchall()
        for record_id, job_id, pid, pgid, birth in rows:
            result = self.stop_process_group(pid, pgid, birth)
            self.event(
                "process",
                {**result, "pid": pid, "pgid": pgid, "job_id": job_id, "process_id": record_id},
            )
            if result["status"] in {"stopped", "already_exited"}:
                self.untrack_process(record_id)

    def artifact_path(self, kind: str = "text") -> tuple[str, Path]:
        ref = new_id("a")
        path = self.artifacts / ref
        path.touch(mode=0o600)
        with self.lock:
            self.db.execute(
                "INSERT INTO artifacts VALUES(?,?,?,?)", (ref, str(path), kind, time.time())
            )
            self.db.commit()
        return ref, path

    def put(self, data: bytes, kind: str = "text") -> str:
        ref, path = self.artifact_path(kind)
        path.write_bytes(data)
        return ref

    def path(self, ref: str) -> Path:
        with self.lock:
            row = self.db.execute("SELECT path FROM artifacts WHERE id=?", (ref,)).fetchone()
        if not row:
            raise Fault("not_found", "Unknown artifact.")
        return Path(row["path"])

    def read(self, ref: str, offset: int = 0, length: int = 8192, binary: bool = False):
        path = self.path(ref)
        if not path.exists():
            raise Fault("expired_artifact", "Artifact was removed or expired.")
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(length)
        size = path.stat().st_size
        return {
            "artifact": ref,
            "offset": offset,
            "size": size,
            "next": offset + len(data) if offset + len(data) < size else None,
            "encoding": "base64" if binary else "utf-8",
            "data": base64.b64encode(data).decode() if binary else data.decode("utf-8", "replace"),
        }

    def bound(self, result):
        raw = encode(result).encode()
        if len(raw) <= BUDGET:
            return result
        return {
            "status": result.get("status", "ok") if isinstance(result, dict) else "ok",
            "artifact": self.put(raw, "application/json"),
            "bytes": len(raw),
            "preview": raw[:2048].decode("utf-8", "replace"),
            "complete": False,
        }

    def auth_block(self, key: str, status: str = "", clear: bool = False) -> str | None:
        with self.lock:
            if clear:
                self.db.execute("DELETE FROM auth_blocks WHERE key=?", (key,))
            elif status:
                self.db.execute("INSERT OR REPLACE INTO auth_blocks VALUES(?,?)", (key, status))
            self.db.commit()
            row = self.db.execute("SELECT status FROM auth_blocks WHERE key=?", (key,)).fetchone()
            return row[0] if row else None
