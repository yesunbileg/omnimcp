"""Private SQLite state and immutable artifacts. No command arguments in events."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .registry import Fault

BUDGET = 16 * 1024


def state_dir() -> Path:
    return Path(
        os.environ.get("AGENTIC_OS_STATE_DIR")
        or Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        / "agentic-os-mcp"
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
        self.db = sqlite3.connect(self.root / "state.sqlite3", check_same_thread=False)
        os.chmod(self.root / "state.sqlite3", 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, action TEXT, status TEXT, created REAL,
                updated REAL, result TEXT, progress TEXT);
            CREATE TABLE IF NOT EXISTS events (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY, path TEXT, kind TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS auth_blocks (key TEXT PRIMARY KEY, status TEXT);
        """)
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
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",
                (ref, action, "queued", time.time(), time.time(), None, None),
            )
            self.db.commit()
        self.event("job", {"job_id": ref, "status": "queued", "action": action})
        return ref

    def update_job(self, ref: str, status: str, result=None, progress=None):
        with self.lock:
            self.db.execute(
                "UPDATE jobs SET status=?, updated=?, result=COALESCE(?,result), "
                "progress=COALESCE(?,progress) WHERE id=?",
                (
                    status,
                    time.time(),
                    encode(result) if result is not None else None,
                    encode(progress) if progress is not None else None,
                    ref,
                ),
            )
            self.db.commit()
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
