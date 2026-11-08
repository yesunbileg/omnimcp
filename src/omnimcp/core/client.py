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
    if os.environ.get("OMNIMCP_SOCKET"):
        return Path(os.environ["OMNIMCP_SOCKET"])
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return runtime / "omnimcp-core" / "worker.sock"


def rpc(request: dict, timeout: float = 125):
    path = socket_path()
    raw = encode(request).encode() + b"\n"
    if len(raw) > MAX_REQUEST:
        return {
            "status": "invalid_params",
            "message": "Request exceeds 1 MiB; split the operation.",
        }
    stage = "connect"
    sent = False
    try:
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise Fault(
                "permission_required", "Worker socket must be owned by this user and mode 0600."
            )
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(timeout)
            sock.connect(str(path))
            stage = "write"
            sent = True
            sock.sendall(raw)
            stage = "read"
            with sock.makefile("rb") as stream:
                result = stream.readline(MAX_REQUEST)
            if not result and sent:
                return {
                    "status": "client_disconnected",
                    "message": (
                        "Worker disconnected after the request was sent; outcome is unknown. "
                        "Inspect job/state before retrying a change."
                    ),
                }
            if not result.endswith(b"\n"):
                raise Fault("backend_error", "Invalid or oversized worker reply.")
            return json.loads(result)
    except Fault as exc:
        return exc.result()
    except TimeoutError as exc:
        if stage == "connect":
            message = (
                "Timed out connecting to worker; request was not sent. "
                "Check worker status before retrying."
            )
        elif stage == "write":
            message = (
                "Timed out sending request; delivery is uncertain. "
                "Inspect job/state before retrying a change."
            )
        else:
            message = (
                "Timed out waiting for worker reply; outcome is unknown. "
                "Inspect job/state before retrying a change."
            )
        return {"status": "client_timeout", "message": f"{message} ({exc})."}
    except ValueError as exc:
        return {"status": "backend_error", "message": f"Invalid worker reply: {exc}"}
    except OSError as exc:
        if sent:
            return {
                "status": "client_disconnected",
                "message": (
                    "Worker connection ended after the request was sent; outcome is unknown. "
                    f"Inspect job/state before retrying a change. ({exc})"
                ),
            }
        return {
            "status": "worker_unavailable",
            "message": f"{exc}. Check OmniMCP worker status; install it if it is not configured.",
        }
