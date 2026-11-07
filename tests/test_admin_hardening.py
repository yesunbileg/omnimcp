import os
import signal
import threading
import time

import pytest

from omnimcp.core.execution import Context
from omnimcp.core.registry import Fault
from omnimcp.core.state import Store


def _admin_env(monkeypatch, tmp_path):
    calls = tmp_path / "calls"
    fake = tmp_path / "pkexec"
    fake.write_text(f'#!/bin/sh\nprintf x >> "{calls}"\nsleep 0.2\nexit 126\n')
    fake.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("WAYLAND_DISPLAY", "test-display")
    return calls


def test_auth_retry_cannot_clear_cancel_block_and_block_survives_restart(tmp_path, monkeypatch):
    calls = _admin_env(monkeypatch, tmp_path)
    state = tmp_path / "state"
    store = Store(state)
    assert Context(store).run(["/usr/bin/true"], admin=True)["status"] == "auth_cancelled"
    store.close()

    reopened = Store(state)
    with pytest.raises(Fault, match="operator reset"):
        Context(reopened, auth_retry=True).run(["/usr/bin/true"], admin=True)
    assert calls.read_text() == "x"
    assert reopened.auth_block("gui-auth") == "auth_cancelled"
    reopened.close()


def test_admin_attempt_lock_denies_concurrent_fanout(tmp_path, monkeypatch):
    store = Store(tmp_path / "state")
    calls = _admin_env(monkeypatch, tmp_path)
    first = Context(store)
    results = []
    thread = threading.Thread(
        target=lambda: results.append(first.run(["/usr/bin/true"], admin=True))
    )
    thread.start()
    deadline = time.monotonic() + 2
    while not calls.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    with pytest.raises(Fault, match="Another admin attempt"):
        Context(store).run(["/usr/bin/true"], admin=True)
    try:
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert calls.read_text() == "x"
    finally:
        if thread.is_alive():
            thread.join(timeout=2)
        store.close()


def test_worker_auth_reset_clears_block_locally(tmp_path, monkeypatch, capsys):
    from omnimcp import core_cli

    store = Store(tmp_path / "cli-state")
    store.auth_block("gui-auth", "auth_cancelled")
    monkeypatch.setenv("OMNIMCP_STATE_DIR", str(tmp_path / "cli-state"))
    result = core_cli.worker(["auth-reset"])
    assert result == 0
    assert store.auth_block("gui-auth") is None
    assert "cleared" in capsys.readouterr().out
    store.close()


def test_install_helper_is_manual_guidance_and_never_runs_elevated_copy(tmp_path):
    from omnimcp.adapters import admin

    class ContextSpy:
        def run(self, *args, **kwargs):
            pytest.fail("admin.install_helper must not run privileged commands")

    result = admin.install(ContextSpy())
    assert result["status"] == "permission_required"
    assert "root" in result["guidance"].lower()


def test_non_admin_termination_pending_does_not_block_gui_auth(tmp_path, monkeypatch):
    store = Store(tmp_path / "state")

    def kill_but_report_pending(pid, pgid, birth):
        os.killpg(pgid, signal.SIGKILL)
        time.sleep(0.02)
        return {"status": "termination_pending", "killed": 1}

    monkeypatch.setattr(store, "stop_process_group", kill_but_report_pending)
    try:
        result = Context(store).run(["/usr/bin/sleep", "30"], timeout=0.001, admin=False)
        assert result["status"] == "timeout_pending"
        assert result["still_running"]
        assert not store.auth_block("gui-auth")
    finally:
        store.close()
