import os
import stat
import tempfile
from pathlib import Path

import pytest

from omnimcp import cli_state, private_paths, safety


def test_configured_runtime_directory_is_private_and_keeps_path(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert safety.state_path() == tmp_path / "omnimcp" / "state.json"
    info = (tmp_path / "omnimcp").stat()
    assert info.st_uid == os.getuid()
    assert stat.S_IMODE(info.st_mode) & 0o077 == 0


def test_untrusted_runtime_path_uses_uid_private_fallback(monkeypatch, tmp_path):
    target = tmp_path / "owned-by-other"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(target))
    directory = private_paths.runtime_dir()
    assert directory == private_paths.fallback_dir()
    assert directory.name == f"omnimcp-{os.getuid()}"
    assert stat.S_IMODE(directory.stat().st_mode) & 0o077 == 0


def test_runtime_symlink_is_rejected_without_touching_target(monkeypatch, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "state.json").write_text("keep")
    link = tmp_path / "runtime"
    link.symlink_to(victim, target_is_directory=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(link))
    path = safety.state_path()
    assert path.parent == private_paths.fallback_dir()
    assert (victim / "state.json").read_text() == "keep"


def test_open_private_file_rejects_symlink_before_write(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep")
    link = tmp_path / "lock"
    link.symlink_to(victim)
    with pytest.raises(OSError):
        private_paths.open_private_file(link, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    assert victim.read_text() == "keep"


def test_cli_state_lock_symlink_cannot_truncate_victim(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    victim = tmp_path / "victim"
    victim.write_text("keep")
    lock = cli_state.path().with_suffix(".lock")
    lock.symlink_to(victim)
    cli_state.save()
    assert victim.read_text() == "keep"


def test_beacon_atomic_replace_does_not_follow_state_symlink(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    runtime = tmp_path / "omnimcp"
    runtime.mkdir(mode=0o700)
    victim = tmp_path / "victim"
    victim.write_text("keep")
    (runtime / "state.json").symlink_to(victim)
    safety.init()
    assert victim.read_text() == "keep"
    assert (runtime / "state.json").is_file()
    assert not (runtime / "state.json").is_symlink()
    safety.shutdown()


def test_untrusted_sticky_tempdir_is_not_used_for_fallback(monkeypatch, tmp_path):
    unsafe = tmp_path / "attacker-temp"
    unsafe.mkdir(mode=0o1777)
    unsafe.chmod(0o1777)
    monkeypatch.setenv("TMPDIR", str(unsafe))
    tempfile.tempdir = None
    assert private_paths.fallback_dir().parent == Path("/tmp")


def test_open_private_file_does_not_truncate_unsafe_existing_file(tmp_path):
    target = tmp_path / "broad-mode"
    target.write_text("keep")
    target.chmod(0o644)
    with pytest.raises(PermissionError):
        private_paths.open_private_file(target, os.O_WRONLY | os.O_TRUNC)
    assert target.read_text() == "keep"


def test_open_private_file_stays_anchored_when_parent_is_swapped(tmp_path, monkeypatch):
    original = tmp_path / "original"
    original.mkdir(mode=0o700)
    target = original / "lock"
    target.write_text("keep")
    target.chmod(0o600)
    victim_dir = tmp_path / "victim-dir"
    victim_dir.mkdir(mode=0o700)
    victim = victim_dir / "lock"
    victim.write_text("safe")
    victim.chmod(0o600)

    open_parent = private_paths._open_parent

    def swap_after_open(path):
        fd, name = open_parent(path)
        original.rename(tmp_path / "moved")
        original.symlink_to(victim_dir, target_is_directory=True)
        return fd, name

    monkeypatch.setattr(private_paths, "_open_parent", swap_after_open)
    fd = private_paths.open_private_file(target, os.O_WRONLY | os.O_TRUNC)
    os.close(fd)
    assert (tmp_path / "moved" / "lock").read_text() == ""
    assert victim.read_text() == "safe"


def test_private_file_fifo_is_rejected_without_blocking(tmp_path):
    import subprocess
    import sys

    fifo = tmp_path / "request"
    os.mkfifo(fifo, 0o600)
    probe = """
import os,sys
from pathlib import Path
from omnimcp.private_paths import open_private_file
try:
    fd = open_private_file(Path(sys.argv[1]), os.O_RDONLY)
except OSError:
    sys.exit(0)
os.close(fd)
sys.exit(1)
"""
    result = subprocess.run([sys.executable, "-c", probe, str(fifo)], timeout=3)
    assert result.returncode == 0


def test_atomic_state_write_stays_bound_after_parent_swap(tmp_path, monkeypatch):
    original = tmp_path / "original-state"
    original.mkdir(mode=0o700)
    victim_dir = tmp_path / "victim-state"
    victim_dir.mkdir(mode=0o700)
    victim = victim_dir / "state.json"
    victim.write_text("safe")
    original_open = private_paths._open_parent

    def swap(path):
        fd, name = original_open(path)
        original.rename(tmp_path / "saved-state")
        original.symlink_to(victim_dir, target_is_directory=True)
        return fd, name

    monkeypatch.setattr(private_paths, "_open_parent", swap)
    private_paths.atomic_write_private(original / "state.json", b"updated")
    assert (tmp_path / "saved-state/state.json").read_text() == "updated"
    assert victim.read_text() == "safe"


def test_private_path_rejects_writable_intermediate_ancestor(tmp_path):
    untrusted = tmp_path / "shared"
    untrusted.mkdir(mode=0o777)
    untrusted.chmod(0o777)
    nested = untrusted / "owned"
    nested.mkdir(mode=0o700)
    with pytest.raises(PermissionError):
        private_paths.private_dir(nested / "state")
