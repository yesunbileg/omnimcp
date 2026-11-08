"""Offline retention uses actual artifacts, SQLite state and worker locks."""

import fcntl
import json
import os
import subprocess
import sys
import time

import pytest

from omnimcp.core.registry import Fault
from omnimcp.core.state import Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "state")
    policy = value.root / "retention-policy.json"
    policy.write_text('{"readonly":false,"dry_run":false}')
    policy.chmod(0o600)
    yield value
    value.close()


def age(store, ref, timestamp):
    os.utime(store.path(ref), (timestamp, timestamp))
    store.db.execute("UPDATE artifacts SET created=? WHERE id=?", (timestamp, ref))
    store.db.commit()


def test_retention_previews_then_expires_only_old_artifact_bytes(store):
    from omnimcp.core.retention import prune_artifacts

    old = store.put(b"old")
    fresh = store.put(b"fresh")
    age(store, old, time.time() - 40 * 86400)
    preview = prune_artifacts(store.root)
    assert preview["dry_run"] and preview["selected"] == 1 and preview["removed"] == 0
    assert store.read(old)["data"] == "old"
    result = prune_artifacts(store.root, apply=True)
    assert result["removed"] == 1 and result["freed_bytes"] == 3
    assert store.read(fresh)["data"] == "fresh"
    with pytest.raises(Fault) as expired:
        store.read(old)
    assert expired.value.code == "expired_artifact"
    assert store.db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 2


def test_retained_size_budget_removes_oldest_first(store):
    from omnimcp.core.retention import prune_artifacts

    refs = [store.put(b"x" * size) for size in (10, 20, 30)]
    for i, ref in enumerate(refs):
        age(store, ref, 100 + i)
    result = prune_artifacts(store.root, older_than_days=10**6, max_bytes=35, apply=True)
    assert result["removed"] == 2 and result["remaining_bytes"] == 30
    assert not store.path(refs[0]).exists() and not store.path(refs[1]).exists()
    assert store.path(refs[2]).stat().st_size == 30


def test_recently_modified_artifact_is_not_expired_by_its_creation_time(store):
    from omnimcp.core.retention import prune_artifacts

    ref = store.put(b"recent output")
    store.db.execute("UPDATE artifacts SET created=0 WHERE id=?", (ref,))
    store.db.commit()
    assert prune_artifacts(store.root, apply=True)["removed"] == 0


def test_cleanup_refuses_the_real_worker_state_lock(store):
    from omnimcp.core.retention import prune_artifacts

    ref = store.put(b"keep")
    path = store.root / "worker.lock"
    path.touch(mode=0o600)
    with path.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(Fault) as busy:
            prune_artifacts(store.root, max_bytes=0, apply=True)
    assert busy.value.code == "busy"
    assert store.read(ref)["data"] == "keep"


@pytest.mark.parametrize("unfinished", ["queued", "running", "process"])
def test_unresolved_jobs_and_processes_are_preserved(store, unfinished):
    from omnimcp.core.retention import prune_artifacts

    ref = store.put(b"keep")
    if unfinished == "process":
        store.track_process("", 123456, 123456, 1.0)
    else:
        job = store.create_job("command.exec")
        if unfinished == "running":
            store.update_job(job, "running")
    with pytest.raises(Fault) as busy:
        prune_artifacts(store.root, max_bytes=0, apply=True)
    assert busy.value.code == "busy"
    assert store.path(ref).exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "outside-path"])
def test_malicious_artifact_records_never_delete_external_data(store, tmp_path, kind):
    from omnimcp.core.retention import prune_artifacts

    outside = tmp_path / "user-data"
    outside.write_bytes(b"private")
    outside.chmod(0o600)
    ref = store.put(b"registered")
    path = store.path(ref)
    path.unlink()
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, path)
    else:
        store.db.execute("UPDATE artifacts SET path=? WHERE id=?", (str(outside), ref))
        store.db.commit()
    unrelated = store.artifacts / "unregistered"
    unrelated.write_bytes(b"keep")
    result = prune_artifacts(store.root, max_bytes=0, apply=True)
    assert result["removed"] == 0 and result["skipped"] == 1
    assert outside.read_bytes() == b"private" and unrelated.read_bytes() == b"keep"


@pytest.mark.parametrize("target", ["state", "artifacts", "database", "lock"])
def test_cleanup_refuses_symlinked_storage_components(store, tmp_path, target):
    from omnimcp.core.retention import prune_artifacts

    root = store.root
    if target == "state":
        root = tmp_path / "alias"
        root.symlink_to(store.root, target_is_directory=True)
    elif target == "artifacts":
        store.artifacts.rmdir()
        store.artifacts.symlink_to(tmp_path, target_is_directory=True)
    elif target == "database":
        path = store.root / "state.sqlite3"
        moved = store.root / "original.sqlite3"
        path.rename(moved)
        path.symlink_to(moved)
    else:
        (store.root / "worker.lock").symlink_to(tmp_path / "other-lock")
    with pytest.raises(Fault) as unsafe:
        prune_artifacts(root, max_bytes=0, apply=True)
    assert unsafe.value.code == "permission_required"


@pytest.mark.parametrize(
    "options", [{"older_than_days": -1}, {"older_than_days": float("nan")}, {"max_bytes": -1}]
)
def test_invalid_limits_do_not_remove_data(store, options):
    from omnimcp.core.retention import prune_artifacts

    ref = store.put(b"keep")
    with pytest.raises(Fault) as invalid:
        prune_artifacts(store.root, apply=True, **options)
    assert invalid.value.code == "invalid_params"
    assert store.path(ref).exists()


def test_prune_cli_previews_by_default_and_requires_apply(store):
    ref = store.put(b"output")
    env = {**os.environ, "OMNIMCP_STATE_DIR": str(store.root)}
    command = [sys.executable, "-m", "omnimcp", "worker", "prune", "--max-bytes", "0"]
    preview = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["selected"] == 1
    assert store.path(ref).exists()
    applied = subprocess.run(
        command + ["--apply"], env=env, capture_output=True, text=True, timeout=5
    )
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["removed"] == 1
    assert not store.path(ref).exists()


@pytest.mark.parametrize("policy", ["OMNIMCP_READONLY", "OMNIMCP_DRYRUN"])
def test_prune_cli_respects_readonly_and_dry_run_policy(store, policy):
    ref = store.put(b"keep")
    env = {**os.environ, "OMNIMCP_STATE_DIR": str(store.root), policy: "1"}
    result = subprocess.run(
        [sys.executable, "-m", "omnimcp", "worker", "prune", "--apply", "--max-bytes", "0"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert json.loads(result.stdout)["status"] == "permission_required"
    assert store.path(ref).exists()


def test_preview_does_not_create_a_missing_state_directory(tmp_path):
    from omnimcp.core.retention import prune_artifacts

    root = tmp_path / "absent"
    with pytest.raises(Fault) as missing:
        prune_artifacts(root)
    assert missing.value.code == "not_found"
    assert not root.exists()


def test_other_worker_operations_reject_prune_flags(monkeypatch):
    from omnimcp import core_cli

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid prune flags must be rejected before systemctl is called")

    monkeypatch.setattr(core_cli.subprocess, "run", unexpected)
    with pytest.raises(SystemExit) as usage:
        core_cli.worker(["status", "--apply"])
    assert usage.value.code == 2


def test_legacy_job_process_identity_blocks_retention_before_backfill(store):
    from omnimcp.core.retention import prune_artifacts

    ref = store.put(b"unresolved output")
    job = store.create_job("command.exec")
    store.update_job(job, "succeeded")
    store.db.execute("UPDATE jobs SET pid=123456,pgid=123456,create_time=1 WHERE id=?", (job,))
    store.db.commit()
    with pytest.raises(Fault) as busy:
        prune_artifacts(store.root, max_bytes=0, apply=True)
    assert busy.value.code == "busy"
    assert store.path(ref).exists()


def test_worker_does_not_backfill_state_before_acquiring_its_lock(store, tmp_path):
    job = store.create_job("command.exec")
    store.update_job(job, "succeeded")
    store.db.execute("UPDATE jobs SET pid=123456,pgid=123456,create_time=1 WHERE id=?", (job,))
    store.db.commit()
    path = store.root / "worker.lock"
    path.touch(mode=0o600)
    with path.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            [sys.executable, "-m", "omnimcp.core.worker"],
            env={
                **os.environ,
                "OMNIMCP_STATE_DIR": str(store.root),
                "OMNIMCP_SOCKET": str(tmp_path / "worker.sock"),
            },
            capture_output=True,
            text=True,
            timeout=5,
        )
    assert result.returncode != 0 and "Another worker" in result.stderr
    assert store.db.execute("SELECT COUNT(*) FROM processes").fetchone()[0] == 0


@pytest.mark.parametrize("policy", ["OMNIMCP_READONLY", "OMNIMCP_DRYRUN"])
def test_prune_honors_installed_worker_policy_from_a_later_normal_shell(
    store, tmp_path, monkeypatch, capsys, policy
):
    from omnimcp import core_cli

    ref = store.put(b"keep")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("OMNIMCP_STATE_DIR", str(store.root))
    monkeypatch.setenv(policy, "1")
    monkeypatch.setattr(
        core_cli.subprocess, "run", lambda argv: subprocess.CompletedProcess(argv, 0)
    )
    assert core_cli.worker(["install"]) == 0
    unit = tmp_path / "config/systemd/user/omnimcp.service"
    assert f"{policy}=1" in unit.read_text()
    capsys.readouterr()
    monkeypatch.delenv(policy)
    assert core_cli.worker(["prune", "--apply", "--max-bytes", "0"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "permission_required"
    assert store.path(ref).exists()


def test_apply_requires_known_worker_retention_policy(store):
    from omnimcp.core.retention import prune_artifacts

    ref = store.put(b"keep")
    (store.root / "retention-policy.json").unlink()
    assert prune_artifacts(store.root, max_bytes=0)["selected"] == 1
    with pytest.raises(Fault) as unknown:
        prune_artifacts(store.root, max_bytes=0, apply=True)
    assert unknown.value.code == "permission_required"
    assert store.path(ref).exists()


@pytest.mark.parametrize(
    "contents", ["invalid JSON", '{"readonly":false}', '{"readonly":"false","dry_run":false}']
)
def test_malformed_retention_policy_blocks_deletion(store, contents):
    from omnimcp.core.retention import prune_artifacts

    ref = store.put(b"keep")
    (store.root / "retention-policy.json").write_text(contents)
    with pytest.raises(Fault) as invalid:
        prune_artifacts(store.root, max_bytes=0, apply=True)
    assert invalid.value.code == "permission_required"
    assert store.path(ref).exists()


def test_symlinked_retention_policy_blocks_deletion(store, tmp_path):
    from omnimcp.core.retention import prune_artifacts

    ref = store.put(b"keep")
    policy = store.root / "retention-policy.json"
    outside = tmp_path / "outside-policy"
    policy.rename(outside)
    policy.symlink_to(outside)
    with pytest.raises(Fault) as unsafe:
        prune_artifacts(store.root, max_bytes=0, apply=True)
    assert unsafe.value.code == "permission_required"
    assert store.path(ref).exists()
