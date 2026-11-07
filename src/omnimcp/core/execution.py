"""Cancellable subprocesses and GUI-only privilege elevation."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from .registry import Fault
from .state import Store

_admin_attempt_lock = threading.Lock()


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
    termination: dict | None = None
    process_identity: tuple[int, int, float] | None = None
    stop_requested: bool = False
    process_lock: threading.Lock = field(default_factory=threading.Lock)

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
        if admin and not _admin_attempt_lock.acquire(blocking=False):
            raise Fault(
                "busy", "Another admin attempt is in progress; no additional prompt was issued."
            )
        try:
            return self._run(argv, cwd=cwd, timeout=timeout, admin=admin, accepted=accepted)
        finally:
            if admin:
                _admin_attempt_lock.release()

    def _run(
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
            if self.store.auth_block(key):
                raise Fault(
                    "auth_cancelled",
                    "Previous authentication stopped. An operator reset is required with "
                    "omnimcp worker auth-reset before retrying.",
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
        process_record = None
        ref, path = self.store.artifact_path("command-output")
        if self.job_id:
            self.progress({"output": ref})
        with path.open("wb") as output:
            with self.process_lock:
                self.check()
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
                    self.process_identity = (proc.pid, proc.pid, birth)
                    if self.cancelled.is_set():

                        def terminate_late():
                            self.termination = self.store.stop_process_group(
                                proc.pid, proc.pid, birth
                            )

                        threading.Thread(target=terminate_late, daemon=True).start()
            if birth is not None:
                try:
                    process_record = (
                        self.store.track_process(self.job_id, proc.pid, proc.pid, birth)
                        or self.job_id
                    )
                except BaseException:
                    self.store.stop_process_group(proc.pid, proc.pid, birth)
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
                if (
                    stopped or self.cancelled.is_set() or proc.poll() is None
                ) and birth is not None:
                    termination = self.store.stop_process_group(proc.pid, proc.pid, birth)
                    self.termination = termination
                    signal_denied = termination["status"] in {
                        "termination_denied",
                        "termination_pending",
                    }
                    if not signal_denied:
                        with contextlib.suppress(subprocess.TimeoutExpired):
                            proc.wait(timeout=1)
                elif proc.poll() is None:
                    signal_denied = True
                if proc.poll() is not None and not signal_denied and process_record:
                    self.store.untrack_process(process_record)
        if signal_denied:
            # Keep the process record until every verified group member has exited.
            if admin:
                self.store.auth_block(key, "cancelled")
            return {
                "status": "cancellation_pending" if stopped == "cancelled" else "timeout_pending",
                "pid": proc.pid,
                "process_ref": process_record,
                "still_running": True,
                "output": ref,
                "message": "Process termination could not be confirmed; inspect actual state. "
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
