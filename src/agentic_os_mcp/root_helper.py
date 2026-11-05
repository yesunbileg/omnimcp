#!/usr/bin/python3 -I
"""Standalone root-owned helper; no imports from user-writable Python packages.

Install to /usr/local/libexec/agentic-os-mcp-file-helper (root:root, 0755).
Every invocation is authorized by pkexec, never by a cached user-written token.
"""

import hashlib
import json
import os
import stat
import sys
import tempfile
import uuid
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if os.geteuid() != 0 or "PKEXEC_UID" not in os.environ:
        raise ValueError("Must be started with pkexec.")
    uid = int(os.environ["PKEXEC_UID"])
    request_path = Path(sys.argv[1])
    info = request_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise ValueError("Request must be a private regular file owned by the invoking user.")
    if info.st_size > 1024 * 1024:
        raise ValueError("Request exceeds 1 MiB.")
    request = json.loads(request_path.read_bytes())
    if set(request) - {"path", "text", "expected_revision", "restore"}:
        raise ValueError("Unknown request fields.")
    path = Path(request["path"])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("Choose an existing regular absolute path; symlinks are refused.")
    original = path.read_bytes()
    info = path.stat()
    revision = digest(original)
    if revision != request["expected_revision"]:
        print(json.dumps({"status": "stale_revision", "revision": revision}))
        return
    root = Path("/var/lib/agentic-os-mcp/backups") / str(uid)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    if "restore" in request:
        token = request["restore"]
        if (
            not isinstance(token, str)
            or len(token) != 32
            or any(c not in "0123456789abcdef" for c in token)
        ):
            raise ValueError("Invalid backup token.")
        saved = json.loads((root / (token + ".json")).read_bytes())
        if saved["path"] != str(path):
            raise ValueError("Backup path does not match.")
        updated = (root / (token + ".data")).read_bytes()
        if digest(updated) != saved["revision"]:
            raise ValueError("Backup digest does not match.")
    else:
        updated = request["text"].encode()
    token = uuid.uuid4().hex
    backup = root / (token + ".data")
    backup.write_bytes(original)
    backup.chmod(0o600)
    metadata = root / (token + ".json")
    metadata.write_text(json.dumps({"path": str(path), "revision": revision}))
    metadata.chmod(0o600)
    if backup.read_bytes() != original:
        raise ValueError("Backup verification failed.")
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
        for key in os.listxattr(path):
            value = os.getxattr(path, key)
            try:
                if os.getxattr(name, key) == value:
                    continue
            except OSError:
                pass
            os.setxattr(name, key, value)
        if path.is_symlink() or digest(path.read_bytes()) != revision:
            print(json.dumps({"status": "stale_revision"}))
            return
        os.replace(name, path)
        parent = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        actual = digest(path.read_bytes())
        print(
            json.dumps(
                {
                    "status": "ok" if actual == digest(updated) else "verification_failed",
                    "revision": actual,
                    "backup": token,
                    "verified": actual == digest(updated),
                }
            )
        )
    finally:
        Path(name).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "backend_error", "message": str(exc)}))
        sys.exit(1)
