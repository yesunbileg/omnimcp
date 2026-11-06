"""Cancellable subprocesses and GUI-only privilege elevation."""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from .registry import Fault
from .state import Store


def flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}


@dataclass
class Context:
    store: Store
    cancelled: threading.Event = field(default_factory=threading.Event)
    job_id: str = ""
    auth_retry: bool = False
    engine: object = None
    deadline: float = float("inf")

    def check(self):
        if time.monotonic() >= self.deadline:
            raise Fault("timeout", "Execution deadline reached; inspect state before retrying.")
        if self.cancelled.is_set():
            raise Fault(
                "cancelled", "Cancellation requested; inspect state before retrying changes."
            )

    def progress(self, value):
        if self.job_id:
            self.store.update_job(self.job_id, "running", progress=value)

    def sleep(self, seconds: float):
        self.cancelled.wait(min(seconds, max(0, self.deadline - time.monotonic())))
        self.check()

    def run(
        self,
        argv: list[str],
        *,
        cwd: str = "",
        timeout: float = 60,
        admin: bool = False,
        accepted: tuple[int, ...] = (0,),
    ) -> dict:
        self.check()
        if not argv or not all(isinstance(a, str) and "\0" not in a for a in argv):
            raise Fault("invalid_params", "argv must contain nonempty executable and strings.")
        executable = shutil.which(argv[0])
        if not executable:
            raise Fault("missing_dependency", f"Executable not found: {argv[0]}")
        argv = [executable, *argv[1:]]
        key = "gui-auth"
        if admin:
            from omnimcp import session

            try:
                session.ensure_session_env()
            except RuntimeError as exc:
                raise Fault("permission_required", str(exc)) from exc
            if self.store.auth_block(key) and not self.auth_retry:
                raise Fault(
                    "auth_cancelled",
                    "Previous authentication stopped. Ask the human before "
                    "retrying; only then set auth_retry=true.",
                )
            if self.auth_retry:
                self.store.auth_block(key, clear=True)
                self.auth_retry = (
                    False  # one explicit human-authorized retry, never a session bypass
                )
            if not shutil.which("pkexec"):
                raise Fault(
                    "missing_dependency", "pkexec is required for graphical authentication."
                )
            if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                raise Fault(
                    "permission_required", "No graphical session selected for authentication."
                )
            argv = [shutil.which("pkexec"), *argv]
        ref, path = self.store.artifact_path("command-output")
        if self.job_id:
            self.progress({"output": ref})
        with path.open("wb") as output:
            proc = subprocess.Popen(
                argv,
                cwd=str(Path(cwd).expanduser()) if cwd else None,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "SYSTEMD_PAGER": "cat", "PAGER": "cat"},
            )
            try:
                birth = psutil.Process(proc.pid).create_time()
            except psutil.NoSuchProcess:
                birth = None
            if birth is not None:
                try:
                    self.store.track_process(self.job_id, proc.pid, proc.pid, birth)
                except BaseException:
                    if proc.poll() is None:
                        with contextlib.suppress(ProcessLookupError, PermissionError):
                            os.killpg(proc.pid, signal.SIGTERM)
                        try:
                            proc.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            try:
                                current = psutil.Process(proc.pid)
                                if (current.create_time() == birth
                                        and current.status() != psutil.STATUS_ZOMBIE
                                        and os.getpgid(proc.pid) == proc.pid):
                                    os.killpg(proc.pid, signal.SIGKILL)
                                    proc.wait()
                            except (psutil.Error, ProcessLookupError, PermissionError):
                                pass
                    raise
            started = time.monotonic()
            stopped = ""
            signal_denied = False
            try:
                while proc.poll() is None:
                    if self.cancelled.wait(0.03):
                        stopped = "cancelled"
                        break
                    if time.monotonic() - started > timeout or time.monotonic() >= self.deadline:
                        stopped = "auth_timeout" if admin else "timeout"
                        break
            finally:
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        signal_denied = True
                    if not signal_denied:
                        try:
                            proc.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                                proc.wait()
                            except ProcessLookupError:
                                proc.wait()
                            except PermissionError:
                                signal_denied = True
                if proc.poll() is not None:
                    self.store.untrack_process(self.job_id)
        if signal_denied:
            # Elevated processes may reject this user's signals; never claim termination.
            self.store.auth_block(key, "cancelled")
            return {
                "status": "cancellation_pending" if stopped == "cancelled" else "timeout_pending",
                "pid": proc.pid,
                "still_running": proc.poll() is None,
                "output": ref,
                "message": "OS denied termination after elevation; inspect actual state. "
                "No retry or additional authentication prompt was issued.",
            }
        result = {
            "status": "ok" if proc.returncode in accepted else "failed",
            "exit_code": proc.returncode,
            "output": ref,
            "text": self.store.read(ref)["data"],
            "bytes": path.stat().st_size,
        }
        if stopped:
            result["status"] = stopped
        elif admin and proc.returncode in (126, 127):
            result["status"] = "auth_cancelled" if proc.returncode == 126 else "permission_required"
        if admin and result["status"] in {"auth_cancelled", "auth_timeout", "cancelled"}:
            self.store.auth_block(key, result["status"])
        return result


def require_ok(result: dict):
    if result.get("status") != "ok":
        raise Fault(
            result.get("status", "failed"), "Backend command did not succeed.", result=result
        )
    return result
