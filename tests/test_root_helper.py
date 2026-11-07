import json
import os
import stat

import pytest

from omnimcp import root_helper


def fixture_tree(tmp_path):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    target_dir = root / "etc"
    target_dir.mkdir(mode=0o755)
    target = target_dir / "settings.json"
    target.write_text('{"old": true}')
    target.chmod(0o600)
    policy = root / "allowed-configs.json"
    policy.write_text(json.dumps([str(target.resolve())]))
    policy.chmod(0o600)
    backups = root / "backups"
    backups.mkdir(mode=0o700)
    return root, target, policy, backups


def test_helper_updates_only_exact_policy_target_and_can_restore(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    uid = os.getuid()
    os.chown(target, uid, os.getgid())
    os.chown(policy, uid, os.getgid())
    receipt = root_helper.apply_request(
        {
            "path": str(target),
            "expected_revision": root_helper.digest(target.read_bytes()),
            "text": "new",
        },
        trusted_uid=uid,
        policy_path=policy,
        backup_base=backups,
        trust_root=str(root),
    )
    assert receipt["verified"] and target.read_text() == "new"
    restored = root_helper.apply_request(
        {
            "path": str(target),
            "expected_revision": receipt["revision"],
            "restore": receipt["backup"],
        },
        trusted_uid=uid,
        policy_path=policy,
        backup_base=backups,
        trust_root=str(root),
    )
    assert restored["verified"] and target.read_text() == '{"old": true}'


def test_helper_rejects_unlisted_path_even_if_root_owned(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    other = root / "etc" / "other"
    other.write_text("old")
    uid = os.getuid()
    os.chown(target, uid, os.getgid())
    os.chown(other, uid, os.getgid())
    os.chown(policy, uid, os.getgid())
    with pytest.raises(ValueError, match="allowlist"):
        root_helper.apply_request(
            {"path": str(other), "expected_revision": root_helper.digest(b"old"), "text": "new"},
            trusted_uid=uid,
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )


@pytest.mark.parametrize("target_kind", ["symlink", "directory"])
def test_helper_rejects_unsafe_target(tmp_path, target_kind):
    root, target, policy, backups = fixture_tree(tmp_path)
    candidate = root / "etc" / "link"
    if target_kind == "symlink":
        candidate.symlink_to(target)
    else:
        candidate.mkdir()
    policy.write_text(json.dumps([str(candidate)]))
    uid = os.getuid()
    os.chown(target, uid, os.getgid())
    os.chown(policy, uid, os.getgid())
    with pytest.raises(ValueError):
        root_helper.apply_request(
            {"path": str(candidate), "expected_revision": "0" * 64, "text": "new"},
            trusted_uid=uid,
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )


def test_helper_rejects_target_ancestor_symlink(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    alias = root / "alias"
    alias.symlink_to(target.parent)
    path = alias / target.name
    policy.write_text(json.dumps([str(path)]))
    uid = os.getuid()
    os.chown(target, uid, os.getgid())
    os.chown(policy, uid, os.getgid())
    with pytest.raises(ValueError):
        root_helper.apply_request(
            {"path": str(path), "expected_revision": "0" * 64, "text": "new"},
            trusted_uid=uid,
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )


def test_helper_rejects_malformed_or_writable_policy(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    uid = os.getuid()
    os.chmod(policy, 0o666)
    with pytest.raises(ValueError, match="permissions"):
        root_helper.apply_request(
            {
                "path": str(target),
                "expected_revision": root_helper.digest(target.read_bytes()),
                "text": "new",
            },
            trusted_uid=uid,
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )
    os.chmod(policy, 0o600)
    policy.write_text('{"path": "not-an-array"}')
    with pytest.raises(ValueError, match="JSON array"):
        root_helper.apply_request(
            {
                "path": str(target),
                "expected_revision": root_helper.digest(target.read_bytes()),
                "text": "new",
            },
            trusted_uid=uid,
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )


def test_helper_rejects_symlinked_policy_and_backup_store(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    uid = os.getuid()
    policy_link = root / "policy-link.json"
    policy_link.symlink_to(policy)
    request = {
        "path": str(target),
        "expected_revision": root_helper.digest(target.read_bytes()),
        "text": "new",
    }
    with pytest.raises(ValueError):
        root_helper.apply_request(
            request,
            trusted_uid=uid,
            policy_path=policy_link,
            backup_base=backups,
            trust_root=str(root),
        )
    backup_link = root / "backup-link"
    backup_link.symlink_to(backups)
    with pytest.raises(ValueError):
        root_helper.apply_request(
            request,
            trusted_uid=uid,
            policy_path=policy,
            backup_base=backup_link,
            trust_root=str(root),
        )


def test_helper_rejects_writable_target_ancestor_and_control_targets(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    uid = os.getuid()
    os.chmod(target.parent, 0o777)
    with pytest.raises(ValueError, match="ancestor"):
        root_helper.apply_request(
            {
                "path": str(target),
                "expected_revision": root_helper.digest(target.read_bytes()),
                "text": "new",
            },
            trusted_uid=uid,
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )
    os.chmod(target.parent, 0o755)
    policy.write_text(json.dumps([str(policy)]))
    with pytest.raises(ValueError, match="Control"):
        root_helper.apply_request(
            {"path": str(policy), "expected_revision": "0" * 64, "text": "new"},
            trusted_uid=uid,
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )


def test_helper_can_backup_and_restore_config_larger_than_request_limit(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    original = b"x" * (1024 * 1024 + 10)
    target.write_bytes(original)
    uid = os.getuid()
    receipt = root_helper.apply_request(
        {
            "path": str(target),
            "expected_revision": root_helper.digest(original),
            "text": "small update",
        },
        trusted_uid=uid,
        policy_path=policy,
        backup_base=backups,
        trust_root=str(root),
    )
    assert receipt["verified"] and target.read_text() == "small update"
    restored = root_helper.apply_request(
        {
            "path": str(target),
            "expected_revision": receipt["revision"],
            "restore": receipt["backup"],
        },
        trusted_uid=uid,
        policy_path=policy,
        backup_base=backups,
        trust_root=str(root),
    )
    assert restored["verified"] and target.read_bytes() == original


def test_helper_rejects_double_slash_alias_of_control_path(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    alias = "//" + str(policy).lstrip("/")
    with pytest.raises(ValueError, match="canonical"):
        root_helper.apply_request(
            {"path": alias, "expected_revision": "0" * 64, "text": "new"},
            trusted_uid=os.getuid(),
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )


def test_helper_rejects_fifo_without_blocking(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    fifo = root / "etc" / "settings.fifo"
    os.mkfifo(fifo)
    policy.write_text(json.dumps([str(fifo)]))
    started = __import__("time").monotonic()
    with pytest.raises(ValueError, match="regular"):
        root_helper.apply_request(
            {"path": str(fifo), "expected_revision": "0" * 64, "text": "new"},
            trusted_uid=os.getuid(),
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )
    assert __import__("time").monotonic() - started < 1


def test_helper_backup_tokens_are_isolated_by_invoking_uid(tmp_path):
    root, target, policy, backups = fixture_tree(tmp_path)
    uid = os.getuid()
    request = {
        "path": str(target),
        "expected_revision": root_helper.digest(target.read_bytes()),
        "text": "new",
    }
    receipt = root_helper.apply_request(
        request,
        trusted_uid=uid,
        invoking_uid=uid,
        policy_path=policy,
        backup_base=backups,
        trust_root=str(root),
    )
    with pytest.raises(ValueError):
        root_helper.apply_request(
            {
                "path": str(target),
                "expected_revision": receipt["revision"],
                "restore": receipt["backup"],
            },
            trusted_uid=uid,
            invoking_uid=uid + 1,
            policy_path=policy,
            backup_base=backups,
            trust_root=str(root),
        )


def test_helper_replace_stays_bound_to_open_directory_after_path_swap(tmp_path, monkeypatch):
    root, target, policy, backups = fixture_tree(tmp_path)
    hostile = root / "hostile"
    hostile.mkdir(mode=0o755)
    decoy = hostile / target.name
    decoy.write_text("do not touch")
    original_replace = root_helper.os.replace

    def swap_then_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        target.parent.rename(root / "moved")
        target.parent.mkdir()
        target.parent.rmdir()
        target.parent.symlink_to(hostile)
        return original_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(root_helper.os, "replace", swap_then_replace)
    uid = os.getuid()
    receipt = root_helper.apply_request(
        {
            "path": str(target),
            "expected_revision": root_helper.digest(target.read_bytes()),
            "text": "new",
        },
        trusted_uid=uid,
        invoking_uid=uid,
        policy_path=policy,
        backup_base=backups,
        trust_root=str(root),
    )
    assert receipt["verified"]
    assert (root / "moved" / target.name).read_text() == "new"
    assert decoy.read_text() == "do not touch"


def test_helper_preserves_mode_xattr_and_returns_stale_revision(tmp_path, monkeypatch):
    root, target, policy, backups = fixture_tree(tmp_path)
    target.chmod(0o640)
    try:
        os.setxattr(target, "user.omnimcp-test", b"kept")
    except OSError as exc:
        pytest.skip(f"user xattrs unavailable: {exc}")
    real_write = root_helper._write_new
    calls = 0

    def race_after_backup(dir_fd, name, data, mode):
        nonlocal calls
        real_write(dir_fd, name, data, mode)
        calls += 1
        if calls == 2:
            target.write_text("external edit")

    monkeypatch.setattr(root_helper, "_write_new", race_after_backup)
    result = root_helper.apply_request(
        {
            "path": str(target),
            "expected_revision": root_helper.digest(target.read_bytes()),
            "text": "new",
        },
        trusted_uid=os.getuid(),
        invoking_uid=os.getuid(),
        policy_path=policy,
        backup_base=backups,
        trust_root=str(root),
    )
    assert result["status"] == "stale_revision"
    assert target.read_text() == "external edit"
    monkeypatch.undo()
    receipt = root_helper.apply_request(
        {
            "path": str(target),
            "expected_revision": root_helper.digest(target.read_bytes()),
            "text": "verified",
        },
        trusted_uid=os.getuid(),
        invoking_uid=os.getuid(),
        policy_path=policy,
        backup_base=backups,
        trust_root=str(root),
    )
    assert receipt["verified"]
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert os.getxattr(target, "user.omnimcp-test") == b"kept"
