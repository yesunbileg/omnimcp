"""Explicit, offline maintenance of registered artifact bytes; metadata is retained."""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import re
import sqlite3
import stat
import time
from pathlib import Path

from omnimcp import private_paths

from .registry import Fault
from .state import encode, state_dir

DEFAULT_DAYS = 30
DEFAULT_BYTES = 1024**3
_ARTIFACT_ID = re.compile(r"a[0-9a-f]{16}\Z")


def record_policy(root: Path | None = None, *, readonly: bool, dry_run: bool):
    """Remember effective worker policy for a later maintenance shell."""
    root = root or state_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = private_paths.private_dir(root)
    private_paths.atomic_write_private(
        root / "retention-policy.json", encode({"readonly": readonly, "dry_run": dry_run}).encode()
    )


def _allow_delete(root: Path):
    path = root / "retention-policy.json"
    try:
        _private_file(path)
        fd = private_paths.open_private_file(path, os.O_RDONLY)
        with os.fdopen(fd) as source:
            policy = json.loads(source.read(1025))
        if (
            not isinstance(policy, dict)
            or set(policy) != {"readonly", "dry_run"}
            or any(type(value) is not bool for value in policy.values())
        ):
            raise ValueError("Unknown retention policy format.")
    except (OSError, ValueError):
        raise Fault(
            "permission_required",
            "Missing or unsafe worker retention policy. Start/reinstall the updated worker, "
            "inspect its policy, then stop it before maintenance.",
        ) from None
    if policy["readonly"] or policy["dry_run"]:
        raise Fault(
            "permission_required", "Recorded worker read-only/dry-run policy blocks deletion."
        )


def _private_file(path: Path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
    ):
        raise PermissionError("Unsafe retention state file.")
    return info


@contextlib.contextmanager
def _offline(root: Path):
    private_paths.private_dir(root)
    fd = private_paths.open_private_file(root / "worker.lock", os.O_RDWR | os.O_CREAT)
    try:
        _private_file(root / "worker.lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Fault(
                "busy", "Stop the worker before previewing or applying retention."
            ) from None
        _private_file(root / "state.sqlite3")
        for suffix in ("-wal", "-shm"):
            path = root / ("state.sqlite3" + suffix)
            if path.exists() or path.is_symlink():
                _private_file(path)
        with contextlib.closing(
            sqlite3.connect((root / "state.sqlite3").as_uri() + "?mode=ro", uri=True)
        ) as db:
            if (
                db.execute("SELECT 1 FROM processes LIMIT 1").fetchone()
                or db.execute(
                    "SELECT 1 FROM jobs WHERE status IN ('queued','running') "
                    "OR pid IS NOT NULL OR pgid IS NOT NULL OR create_time IS NOT NULL LIMIT 1"
                ).fetchone()
            ):
                raise Fault(
                    "busy", "Unresolved jobs/processes remain; recover and stop the worker first."
                )
            directory = os.open(root / "artifacts", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                info = os.fstat(directory)
                if info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise PermissionError("Unsafe retention artifact directory.")
                yield db, directory
            finally:
                os.close(directory)
    finally:
        os.close(fd)


def _snapshot(db, directory: int, root: Path):
    files, skipped = [], 0
    for ref, path, created in db.execute("SELECT id,path,created FROM artifacts"):
        if (
            not isinstance(ref, str)
            or not _ARTIFACT_ID.fullmatch(ref)
            or not isinstance(path, str)
            or Path(os.path.abspath(path)) != root / "artifacts" / ref
        ):
            skipped += 1
            continue
        try:
            info = os.stat(ref, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            continue  # Preserve expired references in SQLite.
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or not isinstance(created, (int, float))
            or not math.isfinite(created)
        ):
            skipped += 1
            continue
        files.append((max(created, info.st_mtime), ref, info))
    return sorted(files), skipped


def _prune(root, db, directory, older_than_days, max_bytes, apply):
    files, skipped = _snapshot(db, directory, root)
    total = sum(info.st_size for _, _, info in files)
    remaining, selected = total, []
    cutoff = time.time() - older_than_days * 86400
    for modified, ref, info in files:
        if modified < cutoff or remaining > max_bytes:
            selected.append((ref, info))
            remaining -= info.st_size
    removed = freed = 0
    if apply:
        for ref, before in selected:
            try:
                after = os.stat(ref, dir_fd=directory, follow_symlinks=False)
                if (
                    (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    or not stat.S_ISREG(after.st_mode)
                    or after.st_nlink != 1
                ):
                    skipped += 1
                    continue
                os.unlink(ref, dir_fd=directory)
                removed += 1
                freed += before.st_size
            except FileNotFoundError:
                skipped += 1
    return {
        "status": "ok",
        "dry_run": not apply,
        "selected": len(selected),
        "would_free_bytes": total - remaining,
        "removed": removed,
        "freed_bytes": freed,
        "remaining_bytes": total - freed,
        "planned_remaining_bytes": remaining,
        "skipped": skipped,
    }


def prune_artifacts(
    root: Path | None = None,
    *,
    older_than_days: float = DEFAULT_DAYS,
    max_bytes: int = DEFAULT_BYTES,
    apply: bool = False,
) -> dict:
    """Preview or delete old/over-budget registered files while the worker is stopped."""
    if (
        not math.isfinite(older_than_days)
        or older_than_days < 0
        or not isinstance(max_bytes, int)
        or max_bytes < 0
    ):
        raise Fault("invalid_params", "Retention days and bytes must be finite nonnegative limits.")
    root = Path(os.path.abspath(root or state_dir()))
    if not root.exists() and not root.is_symlink():
        raise Fault("not_found", "Worker state does not exist; no artifacts were removed.")
    try:
        with _offline(root) as (db, directory):
            if apply:
                _allow_delete(root)
            return _prune(root, db, directory, older_than_days, max_bytes, apply)
    except OSError:
        raise Fault(
            "permission_required", "Retention requires trusted private state paths."
        ) from None
    except sqlite3.Error:
        raise Fault(
            "backend_error", "Retention could not read the worker state database."
        ) from None
