#!/usr/bin/python3 -I
"""Standalone root-owned helper. Policy is a root-controlled JSON array of paths."""

import contextlib
import hashlib
import json
import os
import posixpath
import stat
import sys
import uuid

HELPER = "/usr/local/libexec/omnimcp-file-helper"
POLICY = "/etc/omnimcp/allowed-configs.json"
BACKUP_BASE = "/var/lib/omnimcp/backups"
MAX_REQUEST = 1024 * 1024
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(path):
    return (
        isinstance(path, str)
        and path.startswith("/")
        and not path.startswith("//")
        and posixpath.normpath(path) == path
    )


def _trusted_dir(path, uid, trust_root="/", allowed_owners=None):
    """Open each directory without following links and verify its authority."""
    if not _canonical(path):
        raise ValueError("Path must be canonical and absolute.")
    if not _canonical(trust_root) or (
        trust_root != "/"
        and not path.startswith(trust_root.rstrip("/") + "/")
        and path != trust_root
    ):
        raise ValueError("Path is outside the trusted test root.")
    allowed_owners = set(allowed_owners or (uid,))
    fd = os.open("/", DIR_FLAGS)
    current = ""
    try:
        info = os.fstat(fd)
        checking = trust_root == "/"
        if checking and (info.st_uid not in allowed_owners or info.st_mode & 0o022):
            raise ValueError("Path ancestor is not trusted.")
        for part in path.strip("/").split("/") if path != "/" else ():
            try:
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
            except OSError as exc:
                raise ValueError("Path ancestor is missing or a symlink.") from exc
            current += "/" + part
            info = os.fstat(child)
            checking = checking or current == trust_root
            if checking and (info.st_uid not in allowed_owners or info.st_mode & 0o022):
                os.close(child)
                raise ValueError("Path ancestor is not trusted.")
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_file(path, uid, flags=FILE_FLAGS, trust_root="/", allowed_owners=None):
    if not _canonical(path) or path == "/":
        raise ValueError("Path must be a canonical absolute file path.")
    parent_path, name = posixpath.split(path)
    parent = _trusted_dir(parent_path or "/", uid, trust_root, allowed_owners)
    try:
        try:
            fd = os.open(name, flags, dir_fd=parent)
        except OSError as exc:
            raise ValueError("File path is missing or contains a symlink.") from exc
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid:
            os.close(fd)
            raise ValueError("File must be a trusted regular file.")
        return parent, fd, info
    except BaseException:
        os.close(parent)
        raise


def _read_fd(fd, maximum=None):
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    total = 0
    while True:
        chunk = os.read(fd, min(65536, maximum - total + 1) if maximum else 65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if maximum is not None and total > maximum:
            raise ValueError("Request exceeds 1 MiB.")


def _mkdir_child(parent, name, uid, mode):
    with contextlib.suppress(FileExistsError):
        os.mkdir(name, mode=mode, dir_fd=parent)
    try:
        child = os.open(name, DIR_FLAGS, dir_fd=parent)
    except OSError as exc:
        raise ValueError("Backup path is missing or a symlink.") from exc
    info = os.fstat(child)
    if info.st_uid != uid or info.st_mode & 0o022:
        os.close(child)
        raise ValueError("Backup path is not trusted.")
    return child


def _backup_dir(path, uid, trust_root="/"):
    path = os.fspath(path)
    if not _canonical(path):
        raise ValueError("Backup path must be canonical and absolute.")
    if trust_root == "/":
        fd = _trusted_dir("/", uid)
        remaining = path.strip("/").split("/")
    else:
        if path != trust_root and not path.startswith(trust_root.rstrip("/") + "/"):
            raise ValueError("Backup path is outside the trusted test root.")
        fd = _trusted_dir(trust_root, uid, trust_root)
        suffix = path[len(trust_root) :].strip("/")
        remaining = suffix.split("/") if suffix else []
    try:
        for part in remaining:
            child = _mkdir_child(fd, part, uid, 0o700)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _write_new(dir_fd, name, data, mode):
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        mode,
        dir_fd=dir_fd,
    )
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def _apply(
    request,
    *,
    trusted_uid=0,
    invoking_uid=None,
    policy_path=POLICY,
    backup_base=BACKUP_BASE,
    trust_root="/",
):
    if not isinstance(request, dict) or set(request) - {
        "path",
        "text",
        "expected_revision",
        "restore",
    }:
        raise ValueError("Invalid request fields.")
    path = request.get("path")
    if not _canonical(path):
        raise ValueError("Target must be a canonical absolute path.")
    policy_abs = os.path.abspath(os.fspath(policy_path))
    backup_abs = os.path.abspath(os.fspath(backup_base))
    if (
        path in (HELPER, policy_abs, backup_abs)
        or path.startswith(backup_abs.rstrip("/") + "/")
        or path == "/etc/omnimcp"
        or path.startswith("/etc/omnimcp/")
        or path == "/var/lib/omnimcp"
        or path.startswith("/var/lib/omnimcp/")
    ):
        raise ValueError("Control and backup paths cannot be targets.")
    policy_parent, policy_fd, policy_info = _open_file(
        policy_abs, trusted_uid, trust_root=trust_root
    )
    try:
        if policy_info.st_mode & 0o022:
            raise ValueError("Policy permissions are unsafe.")
        policy = json.loads(_read_fd(policy_fd, MAX_REQUEST))
    finally:
        os.close(policy_fd)
        os.close(policy_parent)
    if not isinstance(policy, list) or any(not _canonical(item) for item in policy):
        raise ValueError("Policy must be a JSON array of canonical absolute paths.")
    if path not in policy:
        raise ValueError("Target is not in the root-controlled allowlist.")
    parent_fd, target_fd, original_info = _open_file(path, trusted_uid, trust_root=trust_root)
    try:
        if original_info.st_mode & 0o022:
            raise ValueError("Target permissions are unsafe.")
        original = _read_fd(target_fd)
        revision = digest(original)
        if revision != request.get("expected_revision"):
            return {"status": "stale_revision", "revision": revision}
        backup_uid = trusted_uid if invoking_uid is None else invoking_uid
        backup_store = posixpath.join(backup_abs, str(backup_uid))
        backup_dir = _backup_dir(backup_store, trusted_uid, trust_root=trust_root)
        try:
            if "restore" in request:
                token = request["restore"]
                if (
                    not isinstance(token, str)
                    or len(token) != 32
                    or any(c not in "0123456789abcdef" for c in token)
                ):
                    raise ValueError("Invalid backup token.")
                try:
                    metadata_fd = os.open(token + ".json", FILE_FLAGS, dir_fd=backup_dir)
                except OSError as exc:
                    raise ValueError("Backup token is unavailable to this invoking user.") from exc
                try:
                    metadata = json.loads(_read_fd(metadata_fd, MAX_REQUEST))
                finally:
                    os.close(metadata_fd)
                if metadata != {"path": path, "revision": metadata.get("revision")}:
                    raise ValueError("Backup metadata is invalid.")
                try:
                    data_fd = os.open(token + ".data", FILE_FLAGS, dir_fd=backup_dir)
                except OSError as exc:
                    raise ValueError("Backup data is unavailable.") from exc
                try:
                    updated = _read_fd(data_fd)
                finally:
                    os.close(data_fd)
                if digest(updated) != metadata["revision"]:
                    raise ValueError("Backup digest does not match.")
            else:
                text = request.get("text")
                if not isinstance(text, str) or len(text.encode()) > 1024 * 1024:
                    raise ValueError("Updated text must be a string no larger than 1 MiB.")
                updated = text.encode()
            token = uuid.uuid4().hex
            _write_new(backup_dir, token + ".data", original, 0o600)
            _write_new(
                backup_dir,
                token + ".json",
                json.dumps({"path": path, "revision": revision}).encode(),
                0o600,
            )
            backup_fd = os.open(token + ".data", FILE_FLAGS, dir_fd=backup_dir)
            try:
                if _read_fd(backup_fd) != original:
                    raise ValueError("Backup verification failed.")
            finally:
                os.close(backup_fd)
        finally:
            os.close(backup_dir)
        temp = "." + posixpath.basename(path) + "." + uuid.uuid4().hex
        temp_fd = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            view = memoryview(updated)
            while view:
                view = view[os.write(temp_fd, view) :]
            os.fsync(temp_fd)
            os.fchown(temp_fd, original_info.st_uid, original_info.st_gid)
            os.fchmod(temp_fd, stat.S_IMODE(original_info.st_mode))
            for key in os.listxattr(target_fd):
                value = os.getxattr(target_fd, key)
                try:
                    if os.getxattr(temp_fd, key) == value:
                        continue
                except OSError:
                    pass
                os.setxattr(temp_fd, key, value)
        except BaseException:
            os.close(temp_fd)
            os.unlink(temp, dir_fd=parent_fd)
            raise
        os.close(temp_fd)
        current_fd = os.open(posixpath.basename(path), FILE_FLAGS, dir_fd=parent_fd)
        try:
            if digest(_read_fd(current_fd)) != revision:
                os.unlink(temp, dir_fd=parent_fd)
                return {"status": "stale_revision"}
        finally:
            os.close(current_fd)
        os.replace(temp, posixpath.basename(path), src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
        verified_fd = os.open(posixpath.basename(path), FILE_FLAGS, dir_fd=parent_fd)
        try:
            actual = digest(_read_fd(verified_fd))
        finally:
            os.close(verified_fd)
        return {
            "status": "ok" if actual == digest(updated) else "verification_failed",
            "revision": actual,
            "backup": token,
            "verified": actual == digest(updated),
        }
    finally:
        os.close(target_fd)
        os.close(parent_fd)


def apply_request(
    request,
    *,
    trusted_uid=0,
    invoking_uid=None,
    policy_path=POLICY,
    backup_base=BACKUP_BASE,
    trust_root="/",
):
    """Testable core; production main always supplies the fixed root-controlled paths."""
    return _apply(
        request,
        trusted_uid=trusted_uid,
        invoking_uid=invoking_uid,
        policy_path=policy_path,
        backup_base=backup_base,
        trust_root=trust_root,
    )


def main():
    if os.geteuid() != 0 or "PKEXEC_UID" not in os.environ:
        raise ValueError("Must be started with pkexec.")
    uid = int(os.environ["PKEXEC_UID"])
    request_path = sys.argv[1]
    parent_fd, request_fd, info = _open_file(request_path, uid, allowed_owners=(0, uid))
    try:
        if info.st_mode & 0o077 or info.st_size > MAX_REQUEST:
            raise ValueError("Request must be private and no larger than 1 MiB.")
        request = json.loads(_read_fd(request_fd, MAX_REQUEST))
    finally:
        os.close(request_fd)
        os.close(parent_fd)
    print(json.dumps(_apply(request, invoking_uid=uid)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "backend_error", "message": str(exc)}))
        sys.exit(1)
