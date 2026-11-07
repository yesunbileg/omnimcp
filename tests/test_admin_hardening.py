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


@pytest.mark.parametrize("unsafe", [None, "owner", "writable", "symlink", "directory", "policy"])
def test_admin_availability_checks_helper_policy_and_ancestors(tmp_path, monkeypatch, unsafe):
    import stat
    from pathlib import Path
    from types import SimpleNamespace

    from omnimcp.adapters import admin

    helper = tmp_path / "libexec" / "helper"
    helper.parent.mkdir()
    helper.write_text("standalone")
    policy = tmp_path / "config" / "allowed-configs.json"
    policy.parent.mkdir()
    policy.write_text('["/etc/example.conf"]')
    if unsafe == "symlink":
        helper.unlink()
        helper.symlink_to(policy)
    if unsafe == "directory":
        helper.unlink()
        helper.mkdir()
    if unsafe == "policy":
        policy.write_text('{"not":"an array"}')
    controlled = {helper, policy, *helper.parents, *policy.parents}
    lstat = Path.lstat

    def root_metadata(path):
        info = lstat(path)
        if path not in controlled:
            return info
        mode = info.st_mode & ~0o022
        uid = 0
        if path == helper.parent:
            if unsafe == "owner":
                uid = 12345
            elif unsafe == "writable":
                mode |= stat.S_IWOTH
        return SimpleNamespace(st_mode=mode, st_uid=uid)

    monkeypatch.setattr(admin, "HELPER", helper)
    monkeypatch.setattr(admin, "POLICY", policy)
    monkeypatch.setattr(Path, "lstat", root_metadata)
    result = admin.availability()
    assert result["status"] == ("available" if unsafe is None else "permission_required")


def test_admin_missing_helper_is_reported_without_trying_install(tmp_path, monkeypatch):
    from omnimcp.adapters import admin

    monkeypatch.setattr(admin, "HELPER", tmp_path / "missing")
    # The unsafe /tmp ancestor is rejected before an absent user-side helper could
    # be treated as trusted or automatically installed.
    assert admin.availability()["status"] == "permission_required"


@pytest.mark.parametrize("fail", [False, True])
def test_admin_update_removes_sensitive_request_even_when_backend_raises(tmp_path, fail):
    import json

    from omnimcp.adapters import admin

    store = Store(tmp_path / "state")
    request_paths = []

    class TestContext:
        def __init__(self):
            self.store = store

        def run(self, argv, **kwargs):
            from pathlib import Path

            request_path = Path(argv[-1])
            request_paths.append(request_path)
            assert json.loads(request_path.read_text())["text"] == "secret fixture value"
            assert kwargs["admin"] is True
            if fail:
                raise RuntimeError("fixture backend failed")
            return {
                "status": "ok",
                "text": json.dumps(
                    {"status": "ok", "verified": True, "revision": "new", "backup": "token"}
                ),
            }

    try:
        if fail:
            with pytest.raises(RuntimeError):
                admin.update(TestContext(), "/etc/example.conf", "old", "secret fixture value")
        else:
            result = admin.update(TestContext(), "/etc/example.conf", "old", "secret fixture value")
            assert result["undo"]["params"]["restore"] == "token"
        assert request_paths and not request_paths[0].exists()
    finally:
        store.close()
