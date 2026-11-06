"""Revision-checked file updates, verified backups and atomic replacement."""

from __future__ import annotations

import ctypes
import difflib
import errno
import fcntl
import hashlib
import json
import os
import secrets
import stat
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

from omnimcp.core.registry import Fault


def path_of(path: str) -> Path:
    p = Path(path).expanduser().absolute()
    if p.is_symlink():
        raise Fault("invalid_params", "Select the symlink target explicitly.")
    return p


def revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def current(p: Path):
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return b"", "missing", None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise Fault("invalid_params", "Select the symlink target explicitly.") from exc
        raise
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise Fault("unsupported", "Only regular files are supported by this action.")
        chunks = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        path_info = os.stat(p, follow_symlinks=False)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or (
            before.st_dev,
            before.st_ino,
        ) != (path_info.st_dev, path_info.st_ino):
            raise Fault("stale_revision", "File changed while reading; re-read.")
        return data, revision(data), after
    finally:
        os.close(fd)


@contextmanager
def _locked_paths(ctx, *paths: Path):
    """Lock canonical path resources in stable order across cooperating calls."""
    locks = ctx.store.root / "file-locks"
    locks.mkdir(mode=0o700, parents=True, exist_ok=True)
    keys = sorted({str(path.parent.resolve() / path.name) for path in paths})
    with ExitStack() as stack:
        for key in keys:
            lock = stack.enter_context((locks / revision(key.encode())).open("a"))
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _fsync_dirs(*paths: Path) -> None:
    for parent in sorted({path.parent for path in paths}, key=str):
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Use Linux renameat2 atomically; fail closed when unavailable."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise Fault("unsupported", "Atomic no-overwrite rename is unavailable on this system.")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise Fault("conflict", "Destination already exists.", path=str(destination))
    if code == errno.EXDEV:
        raise Fault("unsupported", "Atomic move across filesystems is not supported.")
    if code in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
        raise Fault("unsupported", "Atomic no-overwrite rename is unavailable on this filesystem.")
    raise OSError(code, os.strerror(code), str(source), str(destination))


def _move_and_sync(source: Path, destination: Path) -> None:
    _rename_noreplace(source, destination)
    try:
        _fsync_dirs(source, destination)
    except OSError as exc:
        details = {"path": str(destination), "rename_completed": True, "verified": False}
        if os.path.lexists(destination):
            details["retained_path"] = str(destination)
        raise Fault(
            "verification_failed",
            "Path moved, but directory sync failed; inspect the reported destination.",
            **details,
        ) from exc


def _same_object(info, expected_info) -> bool:
    return bool(info and expected_info) and (info.st_dev, info.st_ino) == (
        expected_info.st_dev,
        expected_info.st_ino,
    )


def read(ctx, path: str, offset: int = 0, length: int = 8192) -> dict:
    """Read UTF-8 bytes, revision, mode and explicit continuation offset."""
    p = path_of(path)
    if not offset >= 0 or not 1 <= length <= 262144:
        raise Fault("invalid_params", "offset>=0; length=1..262144.")
    # Check the opened object: a path can be swapped after an initial stat.
    try:
        path_before = p.stat()
    except OSError as exc:
        code = "not_found" if exc.errno == errno.ENOENT else "verification_failed"
        raise Fault(code, "File is unavailable for reading.") from exc
    if not stat.S_ISREG(path_before.st_mode):
        raise Fault("unsupported", "Only regular files are supported by this action.")
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise Fault("invalid_params", "Select the symlink target explicitly.") from exc
        if exc.errno in (errno.ENXIO, errno.ENODEV):
            raise Fault("unsupported", "Only regular files are supported by this action.") from exc
        code = "stale_revision" if exc.errno == errno.ENOENT else "verification_failed"
        raise Fault(code, "File changed or became unavailable while opening; re-read.") from exc
    try:
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise Fault("unsupported", "Only regular files are supported by this action.")
            stream.seek(offset)
            data = stream.read(length)
            stream.seek(0)
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            after = os.fstat(stream.fileno())
        path_info = p.stat()
    except OSError as exc:
        code = "stale_revision" if exc.errno == errno.ENOENT else "verification_failed"
        raise Fault(code, "File changed or became unavailable while reading; re-read.") from exc
    if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) != (
        after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size
    ) or (after.st_dev, after.st_ino) != (path_info.st_dev, path_info.st_ino):
        raise Fault("stale_revision", "File changed while reading; re-read.")
    return {
        "status": "ok",
        "path": str(p),
        "revision": digest,
        "size": after.st_size,
        "mode": oct(stat.S_IMODE(after.st_mode)),
        "offset": offset,
        "text": data.decode("utf-8", "replace"),
        "next": offset + len(data) if offset + len(data) < after.st_size else None,
    }


def replace(
    ctx,
    path: str,
    expected_revision: str,
    data: bytes,
    preview: bool = False,
    mode: int | None = None,
) -> dict:
    p = path_of(path)
    with _locked_paths(ctx, p):
        old, rev, info = current(p)
        if rev != expected_revision:
            raise Fault("stale_revision", "Re-read the file before editing.", revision=rev)
        diff = "".join(
            difflib.unified_diff(
                old.decode("utf-8", "replace").splitlines(True),
                data.decode("utf-8", "replace").splitlines(True),
                fromfile=str(p),
                tofile=str(p),
            )
        )
        if preview:
            return {"status": "ok", "preview": True, "revision": rev, "diff": diff}
        backup_data = ctx.store.put(old, "backup-bytes")
        manifest = {
            "path": str(p),
            "data": backup_data,
            "revision": rev,
            "mode": stat.S_IMODE(info.st_mode) if info else 0o600,
        }
        backup = ctx.store.put(json.dumps(manifest).encode(), "backup-manifest")
        if ctx.store.path(backup_data).read_bytes() != old:
            raise Fault("verification_failed", "Backup verification failed; file unchanged.")
        fd, name = tempfile.mkstemp(prefix=f".{p.name}.", dir=p.parent)
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                if info and (info.st_uid != os.getuid() or info.st_gid != os.getgid()):
                    os.fchown(stream.fileno(), info.st_uid, info.st_gid)
                os.fchmod(stream.fileno(), mode if mode is not None else manifest["mode"])
            if info:
                for key in os.listxattr(p):
                    value = os.getxattr(p, key)
                    try:
                        if os.getxattr(temp, key) == value:
                            continue  # Includes NTFS3 $LXUID/$LXGID/$LXMOD set by chmod/chown.
                    except OSError:
                        pass
                    os.setxattr(temp, key, value)
            ctx.check()
            if current(p)[1] != rev:
                raise Fault("stale_revision", "File changed before replacement.")
            os.replace(temp, p)
            parent = os.open(p.parent, os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            temp.unlink(missing_ok=True)
        actual = revision(p.read_bytes())
        if actual != revision(data):
            raise Fault("verification_failed", "File differs after replacement.", backup=backup)
        return {
            "status": "ok",
            "path": str(p),
            "revision": actual,
            "backup": backup,
            "diff": diff,
            "verified": True,
            "undo": {
                "action": "file.restore",
                "params": {"path": str(p), "backup": backup, "expected_revision": actual},
            },
        }


def write(ctx, path: str, text: str, expected_revision: str, preview: bool = False) -> dict:
    """Replace a regular file, or create with expected_revision='missing'."""
    return replace(ctx, path, expected_revision, text.encode(), preview)


def patch(
    ctx,
    path: str,
    before: str,
    after: str,
    expected_revision: str,
    count: int = 1,
    preview: bool = False,
) -> dict:
    """Replace exactly count literal occurrences after a revision check."""
    if not before or count < 1:
        raise Fault("invalid_params", "before must be nonempty and count>=1.")
    data, rev, _ = current(path_of(path))
    if rev != expected_revision:
        raise Fault("stale_revision", "File changed; re-read.", revision=rev)
    text = data.decode("utf-8")
    if text.count(before) != count:
        raise Fault("conflict", f"Expected {count} matches; found {text.count(before)}.")
    return replace(ctx, path, rev, text.replace(before, after).encode(), preview)


def restore(ctx, path: str, backup: str, expected_revision: str) -> dict:
    """Restore a verified backup to its original path, checking current revision."""
    manifest = json.loads(ctx.store.path(backup).read_bytes())
    if manifest["path"] != str(path_of(path)):
        raise Fault("invalid_params", "Backup belongs to a different path.")
    data = ctx.store.path(manifest["data"]).read_bytes()
    if manifest["revision"] == "missing":
        return _undo_creation(ctx, path_of(path), expected_revision)
    if revision(data) != manifest["revision"]:
        raise Fault("verification_failed", "Backup checksum mismatch.")
    return replace(ctx, path, expected_revision, data, mode=manifest["mode"])


def _undo_creation(ctx, path: Path, expected_revision: str) -> dict:
    """Quarantine and verify a created file before removing the checked inode."""
    with _locked_paths(ctx, path):
        data, actual_revision, info = current(path)
        if actual_revision != expected_revision or info is None:
            raise Fault(
                "stale_revision",
                "Created file changed or disappeared; re-read before undoing.",
                revision=actual_revision,
            )
        ctx.check()
        quarantine = path.with_name(f".{path.name}.undo-{secrets.token_hex(12)}")
        _move_and_sync(path, quarantine)
        try:
            moved_data, moved_revision, moved_info = current(quarantine)
        except (Fault, OSError) as exc:
            raise Fault(
                "verification_failed",
                "Quarantined file could not be verified; bytes remain available.",
                retained_path=str(quarantine),
                verified=False,
            ) from exc
        if (
            moved_revision != expected_revision
            or moved_data != data
            or not _same_object(moved_info, info)
        ):
            try:
                _move_and_sync(quarantine, path)
            except (Fault, OSError) as exc:
                if isinstance(exc, Fault) and exc.details.get("rename_completed"):
                    raise
                raise Fault(
                    "conflict",
                    "Created file changed during undo and could not be restored to its path.",
                    retained_path=str(quarantine),
                ) from exc
            raise Fault(
                "stale_revision",
                "Created file changed during undo; original path was restored.",
            )
        try:
            quarantine.unlink()
        except OSError as exc:
            raise Fault(
                "verification_failed",
                "Could not remove the verified undo quarantine; bytes remain available.",
                retained_path=str(quarantine),
            ) from exc
        try:
            _fsync_dirs(path, quarantine)
        except OSError as exc:
            raise Fault(
                "verification_failed",
                "Created file was removed, but directory sync failed; absence is not durable.",
                path=str(path),
                removed=True,
                verified=False,
            ) from exc
        if os.path.lexists(path):
            raise Fault(
                "conflict",
                "Another file appeared at the created path during undo.",
                retained_path=str(path),
            )
        return {
            "status": "ok",
            "path": str(path),
            "revision": "missing",
            "verified": True,
            "removed_revision": actual_revision,
        }


def search(ctx, root: str, pattern: str, glob: str = "", fixed: bool = True) -> dict:
    """Search with ripgrep. Full output is retained in an artifact."""
    argv = ["rg", "--line-number", "--no-heading", "--color=never", "--max-columns=1000"]
    if fixed:
        argv.append("--fixed-strings")
    if glob:
        argv += ["--glob", glob]
    return ctx.run([*argv, "--", pattern, str(Path(root).expanduser())], accepted=(0, 1))


def move(ctx, source: str, destination: str, expected_revision: str) -> dict:
    """Move a regular file with atomic no-overwrite semantics and verified receipt."""
    src, dst = path_of(source), path_of(destination)
    if src.resolve() == dst.resolve():
        raise Fault("invalid_params", "Source and destination must be different paths.")
    with _locked_paths(ctx, src, dst):
        data, rev, info = current(src)
        if rev != expected_revision or rev == "missing" or info is None:
            raise Fault("stale_revision", "Source revision differs.", revision=rev)
        ctx.check()
        _move_and_sync(src, dst)
        try:
            moved_data, moved_revision, moved_info = current(dst)
        except (Fault, OSError) as exc:
            raise Fault(
                "stale_revision",
                "Moved file could not be verified; bytes remain available.",
                retained_path=str(dst),
                verified=False,
            ) from exc
        source_recreated = os.path.lexists(src)
        if (
            moved_revision != rev
            or moved_data != data
            or not _same_object(moved_info, info)
            or source_recreated
        ):
            # Never unlink the source path: it may now belong to a concurrent writer.
            # Roll back only with an atomic no-overwrite move into an absent source name.
            try:
                if _same_object(current(dst)[2], moved_info):
                    _move_and_sync(dst, src)
                    raise Fault(
                        "stale_revision",
                        "Source changed during move; moved file was returned to its original path.",
                    )
            except Fault as exc:
                if exc.code == "stale_revision" or exc.details.get("rename_completed"):
                    raise
                retained = str(dst) if os.path.lexists(dst) else str(src)
            except OSError:
                retained = str(dst) if os.path.lexists(dst) else str(src)
            else:
                retained = str(dst) if os.path.lexists(dst) else str(src)
            raise Fault(
                "stale_revision",
                "Source changed during move; bytes were retained for recovery.",
                retained_path=retained,
                verified=False,
            )
        return {
            "status": "ok",
            "path": str(dst),
            "revision": rev,
            "verified": True,
            "mode": oct(stat.S_IMODE(moved_info.st_mode)),
            "undo": {
                "action": "file.move",
                "params": {
                    "source": str(dst),
                    "destination": str(src),
                    "expected_revision": rev,
                },
            },
        }


def config_update(
    ctx,
    path: str,
    text: str,
    expected_revision: str,
    reload_argv: list[str],
    verify_argv: list[str],
) -> dict:
    """Atomic update followed by explicit user-supplied reload and verification commands."""
    receipt = write(ctx, path, text, expected_revision)
    reload = ctx.run(reload_argv)
    if reload["status"] != "ok":
        return {"status": "reload_failed", "file": receipt, "reload": reload}
    verification = ctx.run(verify_argv)
    return {
        "status": "ok" if verification["status"] == "ok" else "verification_failed",
        "file": receipt,
        "reload": reload,
        "verification": verification,
    }


def register(r):
    def resource(p):
        return ("file:" + str(path_of(p["path"]).resolve()),)

    for name, fn in (("read", read), ("write", write), ("patch", patch), ("restore", restore)):
        r.add(
            f"file.{name}",
            fn,
            readonly=name == "read",
            idempotent=name == "read",
            resources=resource,
            undo="file.restore with returned backup and current revision"
            if name != "read"
            else None,
            verification="SHA-256 revision and verified backup.",
        )
    r.add("file.search", search, readonly=True, idempotent=True, dependencies=("rg",))
    r.add(
        "file.move",
        move,
        resources=lambda p: tuple(
            "file:" + str(path_of(p[k]).resolve()) for k in ("source", "destination")
        ),
        undo="file.move using the returned undo receipt",
    )
    r.add(
        "config.update",
        config_update,
        resources=resource,
        verification="Atomic write, reload exit status and explicit verification command.",
        undo="file.restore; reload restored configuration separately",
    )
