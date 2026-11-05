"""Bounded JSON-line RPC over an owner-only Unix socket."""

from __future__ import annotations

import json
import os
import socket
import stat
from pathlib import Path

from .registry import Fault
from .state import encode

MAX_REQUEST = 1024 * 1024


def socket_path() -> Path:
    if os.environ.get("AGENTIC_OS_SOCKET"):
        return Path(os.environ["AGENTIC_OS_SOCKET"])
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return runtime / "agentic-os-mcp-core" / "worker.sock"


def rpc(request: dict, timeout: float = 125):
    path = socket_path()
    raw = encode(request).encode() + b"\n"
    if len(raw) > MAX_REQUEST:
        return {
            "status": "invalid_params",
            "message": "Request exceeds 1 MiB; split the operation.",
        }
    try:
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise Fault(
                "permission_required", "Worker socket must be owned by this user and mode 0600."
            )
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(timeout)
            sock.connect(str(path))
            sock.sendall(raw)
            with sock.makefile("rb") as stream:
                result = stream.readline(MAX_REQUEST)
            if not result.endswith(b"\n"):
                raise Fault("backend_error", "Invalid or oversized worker reply.")
            return json.loads(result)
    except Fault as exc:
        return exc.result()
    except (OSError, ValueError) as exc:
        return {
            "status": "worker_unavailable",
            "message": f"{exc}. Run agentic-os-mcp worker install/status.",
        }
