"""Process identity and persistent PTYs owned by the worker, never by a bridge."""

from __future__ import annotations

import contextlib
import errno
import os
import pty
import re
import select
import signal
import subprocess
import sys
import threading
from pathlib import Path

import psutil

from omnimcp.core.registry import Fault
from omnimcp.core.state import new_id


class Processes:
    def __init__(self):
        self.refs = {}
        self.prefix = new_id("p")[:5]
        self.terminals = {}
        self.lock = threading.RLock()

    def ref(self, proc):
        identity = proc.pid, proc.create_time()
        with self.lock:
            for ref, saved in self.refs.items():
                if saved == identity:
                    return ref
            ref = self.prefix + str(len(self.refs) + 1)
            self.refs[ref] = identity
            return ref

    def resolve(self, ref):
        with self.lock:
            saved = self.refs.get(ref)
        if saved is None:
            raise Fault("stale_reference", "Process reference expired; observe process.list again.")
        pid, birth = saved
        try:
            proc = psutil.Process(pid)
            if proc.create_time() != birth:
                raise psutil.NoSuchProcess(pid)
        except psutil.NoSuchProcess as exc:
            raise Fault("stale_reference", "Process exited or PID was reused.") from exc
        return proc

    def listing(self, ctx, match: str = "") -> list[dict]:
        """Process tree rows with stable references; signal accepts references, not raw PIDs."""
        rows = []
        for proc in psutil.process_iter(
            ["pid", "ppid", "name", "username", "memory_info", "status"]
        ):
            try:
                info = proc.info
                if match.lower() not in (info["name"] or "").lower():
                    continue
                rows.append(
                    {
                        "ref": self.ref(proc),
                        "pid": proc.pid,
                        "parent": info["ppid"],
                        "name": info["name"],
                        "user": info["username"],
                        "state": info["status"],
                        "rss": info["memory_info"].rss if info["memory_info"] else None,
                        "cpu_seconds": sum(proc.cpu_times()[:2]),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return rows

    def send_signal(self, ctx, ref: str, signal_name: str = "TERM") -> dict:
        """Signal an observed process, checking its creation time immediately before dispatch."""
        if signal_name not in {"TERM", "INT", "HUP", "KILL", "STOP", "CONT", "USR1", "USR2"}:
            raise Fault("invalid_params", "Unsupported signal name.")
        proc = self.resolve(ref)
        if proc.pid in {1, os.getpid()}:
            raise Fault("permission_required", "Refusing to signal init or this worker.")
        proc.send_signal(getattr(signal, "SIG" + signal_name))
        gone = not proc.is_running()
        return {
            "status": "ok",
            "delivered": True,
            "exited": gone,
            "verification": "Signal delivered; exited=false does not imply process termination.",
        }

    def terminal(self, ref):
        with self.lock:
            value = self.terminals.get(ref)
        if value is None:
            raise Fault("stale_reference", "PTY is no longer owned by this worker.")
        return value

    def start(self, ctx, argv: list[str], cwd: str = "") -> dict:
        """Start a persistent user PTY; it survives MCP disconnection, not worker restart."""
        check_command(argv)
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "omnimcp.core.pty_child", *argv],
                cwd=str(Path(cwd).expanduser()) if cwd else None,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
            )
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        ref = new_id("t")
        artifact, path = ctx.store.artifact_path("pty-output")
        value = {
            "proc": proc,
            "master": master,
            "output": artifact,
            "path": path,
            "lock": threading.Lock(),
            "closed": False,
        }
        with self.lock:
            self.terminals[ref] = value

        def drain():
            with path.open("ab", buffering=0) as stream:
                try:
                    while True:
                        ready, _, _ = select.select([master], [], [], 0.1)
                        if ready:
                            data = os.read(master, 65536)
                            if not data:
                                break
                            stream.write(data)
                        elif proc.poll() is not None:
                            break
                except OSError as exc:
                    if exc.errno not in {errno.EIO, errno.EBADF}:
                        raise
                finally:
                    with value["lock"]:
                        value["closed"] = True
                        with contextlib.suppress(OSError):
                            os.close(master)
                    proc.wait()
                    ctx.store.event(
                        "pty", {"ref": ref, "status": "exited", "exit_code": proc.returncode}
                    )

        value["thread"] = threading.Thread(target=drain, daemon=True)
        value["thread"].start()
        return {"status": "ok", "ref": ref, "pid": proc.pid, "output": artifact}

    def status(self, ctx, ref: str) -> dict:
        """Return PTY state and output artifact; artifact offsets are persistent cursors."""
        terminal = self.terminal(ref)
        code = terminal["proc"].poll()
        return {
            "status": "ok",
            "state": "running" if code is None else "exited",
            "exit_code": code,
            "output": terminal["output"],
            "bytes": terminal["path"].stat().st_size,
        }

    def write(self, ctx, ref: str, text: str) -> dict:
        """Write non-secret PTY input. Password prompts must be handled by the human."""
        terminal = self.terminal(ref)
        if len(text.encode()) > 8192:
            raise Fault("invalid_params", "PTY input is limited to 8192 bytes per call.")
        with terminal["path"].open("rb") as stream:
            stream.seek(max(0, terminal["path"].stat().st_size - 512))
            tail = stream.read().decode("utf-8", "replace")
        if re.search(r"(password|passphrase|pin)\s*[^\n]*[:?]\s*$", tail, re.I):
            raise Fault(
                "permission_required",
                "Secret prompt detected. Use a graphical authentication flow.",
            )
        with terminal["lock"]:
            if terminal["closed"] or terminal["proc"].poll() is not None:
                raise Fault("stale_reference", "PTY has exited.")
            os.write(terminal["master"], text.encode())
        return {"status": "ok", "bytes_written": len(text.encode())}

    def stop(self, ctx, ref: str) -> dict:
        """Terminate the PTY process group; query status to verify exit."""
        terminal = self.terminal(ref)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(terminal["proc"].pid, signal.SIGTERM)
        try:
            terminal["proc"].wait(timeout=2)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(terminal["proc"].pid, signal.SIGKILL)
            terminal["proc"].wait(timeout=2)
        return self.status(ctx, ref)

    def close(self):
        for t in list(self.terminals.values()):
            if t["proc"].poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(t["proc"].pid, signal.SIGKILL)
            if "thread" in t:
                t["thread"].join(timeout=3)


def check_command(argv):
    if not argv or not argv[0]:
        raise Fault("invalid_params", "argv must specify a user command.")
    if Path(argv[0]).name in {"sudo", "su", "pkexec", "doas"}:
        raise Fault(
            "permission_required", "Use a semantic admin action with graphical authentication."
        )


def command(
    ctx, argv: list[str], cwd: str = "", timeout_s: float = 3600, resource: str = ""
) -> dict:
    """Run a user command without a shell; retained output and exit status. No implicit retry."""
    check_command(argv)
    if not 0 < timeout_s <= 86400:
        raise Fault("invalid_params", "timeout_s must be within (0,86400].")
    return ctx.run(argv, cwd=cwd, timeout=timeout_s)


def admin_command(
    ctx, argv: list[str], cwd: str = "", timeout_s: float = 3600, resource: str = ""
) -> dict:
    """Run an explicit administrator command using a graphical password popup only.

    Use semantic adapters when available. The caller must verify application state;
    this general escape hatch does not promise undo for arbitrary programs.
    """
    check_command(argv)
    if not 0 < timeout_s <= 86400:
        raise Fault("invalid_params", "timeout_s must be within (0,86400].")
    return ctx.run(argv, cwd=cwd, timeout=timeout_s, admin=True)


def register(r):
    processes = Processes()
    r.close_hooks.append(processes.close)
    r.add(
        "command.exec",
        command,
        resources=lambda p: ("command:" + p["resource"],) if p["resource"] else (),
        verification=(
            "Exit status and full output artifact; caller supplies application verification."
        ),
    )
    r.add(
        "command.admin_exec",
        admin_command,
        dependencies=("pkexec",),
        privilege="GUI admin",
        resources=lambda p: ("command:" + p["resource"],) if p["resource"] else (),
        verification="Exit status and retained output; caller verifies application state.",
    )
    r.add("process.list", processes.listing, readonly=True, idempotent=True)
    r.add("process.signal", processes.send_signal, resources=lambda p: ("process:" + p["ref"],))
    for name, fn in (
        ("start", processes.start),
        ("status", processes.status),
        ("write", processes.write),
        ("stop", processes.stop),
    ):
        r.add(
            "pty." + name,
            fn,
            readonly=name == "status",
            idempotent=name == "status",
            resources=("pty",),
        )
