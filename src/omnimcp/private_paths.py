"""Private runtime directories and files used for per-user coordination."""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from pathlib import Path

_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)


def _open_parent(path: Path) -> tuple[int, str]:
    """Open every directory component without following links; return parent fd and leaf."""
    path = Path(os.path.abspath(path))
    parts = path.parts
    fd = os.open(parts[0], _DIR_FLAGS | getattr(os, "O_NOFOLLOW", 0))
    try:
        root = os.fstat(fd)
        if not stat.S_ISDIR(root.st_mode) or root.st_uid != 0 or root.st_mode & 0o022:
            raise PermissionError("untrusted filesystem root")
        for index, part in enumerate(parts[1:-1], start=1):
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):
                raise NotADirectoryError(path)
            component = str(Path(*parts[: index + 1]))
            child = os.open(part, _DIR_FLAGS | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            safe_owner = info.st_uid in (0, os.getuid())
            safe_mode = not (info.st_mode & 0o022)
            is_safe_tmp = (
                component == "/tmp" and info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            )
            if not stat.S_ISDIR(info.st_mode) or not safe_owner or not (safe_mode or is_safe_tmp):
                raise PermissionError(f"untrusted directory ancestor: {component}")
        leaf = parts[-1]
        return fd, leaf
    except BaseException:
        os.close(fd)
        raise


def _check_private_dir(fd: int, path: Path) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError(f"untrusted private directory: {path}")


def _ensure_dir(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    parent_fd, leaf = _open_parent(path)
    try:
        with contextlib.suppress(FileExistsError):
            os.mkdir(leaf, 0o700, dir_fd=parent_fd)
        fd = os.open(leaf, _DIR_FLAGS | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise PermissionError(f"untrusted private directory: {path}")
            if info.st_mode & 0o077:
                os.fchmod(fd, 0o700)
                _check_private_dir(fd, path)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)
    return path


def fallback_dir() -> Path:
    """Return the UID-specific private directory under trusted system /tmp."""
    return _ensure_dir(Path("/tmp") / f"omnimcp-{os.getuid()}")


def private_dir(path: Path) -> Path:
    """Create or validate an owned private directory under trusted ancestors."""
    return _ensure_dir(Path(path))


def runtime_dir() -> Path:
    """Return XDG_RUNTIME_DIR/omnimcp when trusted, otherwise a private fallback."""
    configured = os.environ.get("XDG_RUNTIME_DIR")
    if configured:
        try:
            base = Path(configured)
            fd, leaf = _open_parent(base / "omnimcp")
            try:
                base_fd = os.open(".", _DIR_FLAGS, dir_fd=fd)
                try:
                    info = os.fstat(base_fd)
                    if (
                        not stat.S_ISDIR(info.st_mode)
                        or info.st_uid != os.getuid()
                        or info.st_mode & 0o077
                    ):
                        raise PermissionError("untrusted XDG_RUNTIME_DIR")
                finally:
                    os.close(base_fd)
            finally:
                os.close(fd)
            return _ensure_dir(base / "omnimcp")
        except OSError:
            pass
    return fallback_dir()


def open_private_file(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open a private regular file through its verified parent directory fd."""
    parent_fd, leaf = _open_parent(path)
    truncate = bool(flags & getattr(os, "O_TRUNC", 0))
    flags &= ~getattr(os, "O_TRUNC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(leaf, flags, mode, dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise PermissionError(f"untrusted private file: {path}")
            if truncate:
                os.ftruncate(fd, 0)
            return fd
        except BaseException:
            os.close(fd)
            raise
    finally:
        os.close(parent_fd)


def atomic_write_private(path: Path, data: bytes) -> None:
    """Atomically replace a private file while anchored to its verified directory."""
    parent_fd, leaf = _open_parent(path)
    temporary = f".omnimcp-{secrets.token_hex(12)}.tmp"
    fd = -1
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent_fd)
        os.close(parent_fd)
