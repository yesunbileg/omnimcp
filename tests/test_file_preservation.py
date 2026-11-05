"""File restore and move operations preserve bytes across pathname races."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentic_os_mcp.adapters import files
from agentic_os_mcp.core.registry import Fault


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        self.artifacts = {}
        self.next_id = 0

    def put(self, data: bytes, kind: str) -> str:
        self.next_id += 1
        ref = f"{kind}-{self.next_id}"
        self.artifacts[ref] = data
        return ref

    def path(self, ref: str) -> Path:
        path = self.root / "artifacts" / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        if ref in self.artifacts:
            path.write_bytes(self.artifacts[ref])
        return path


@pytest.fixture
def ctx(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    store.root.mkdir()
    return SimpleNamespace(store=store, check=lambda: None)


def test_restore_removes_unchanged_new_file(ctx, tmp_path):
    path = tmp_path / "created.txt"
    receipt = files.write(ctx, str(path), "original", "missing")

    result = files.restore(
        ctx,
        str(path),
        receipt["backup"],
        receipt["revision"],
    )

    assert result["status"] == "ok"
    assert result["verified"] is True
    assert not path.exists()


def test_restore_refuses_changed_new_file(ctx, tmp_path):
    path = tmp_path / "created.txt"
    receipt = files.write(ctx, str(path), "original", "missing")
    path.write_bytes(b"user edit")

    with pytest.raises(Fault, match="changed") as error:
        files.restore(ctx, str(path), receipt["backup"], receipt["revision"])

    assert error.value.code == "stale_revision"
    assert path.read_bytes() == b"user edit"


def test_restore_quarantines_and_restores_a_replacement_racing_undo(
    ctx, tmp_path, monkeypatch
):
    path = tmp_path / "created.txt"
    receipt = files.write(ctx, str(path), "original", "missing")
    original_rename = files._rename_noreplace

    def replace_then_quarantine(source, destination):
        if Path(source) == path:
            replacement = tmp_path / "replacement.txt"
            replacement.write_bytes(b"concurrent replacement")
            os.replace(replacement, path)
        return original_rename(source, destination)

    monkeypatch.setattr(files, "_rename_noreplace", replace_then_quarantine)

    with pytest.raises(Fault) as error:
        files.restore(ctx, str(path), receipt["backup"], receipt["revision"])

    assert error.value.code == "stale_revision"
    assert path.read_bytes() == b"concurrent replacement"
    assert list(tmp_path.glob(".created.txt.undo-*")) == []


def test_move_detects_source_replacement_before_atomic_rename(
    ctx, tmp_path, monkeypatch
):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"expected source")
    replacement = tmp_path / "replacement.txt"
    replacement.write_bytes(b"concurrent replacement")
    if hasattr(files, "_rename_noreplace"):
        original_rename = files._rename_noreplace

        def replace_before_rename(src, dst):
            if Path(src) == source:
                os.replace(replacement, source)
            return original_rename(src, dst)

        monkeypatch.setattr(files, "_rename_noreplace", replace_before_rename)
    else:
        # Exercise the old link/verify/unlink boundary: the replacement lands
        # after the link is made but before the old code unlinks the source path.
        original_link = files.os.link

        def replace_after_link(src, dst):
            original_link(src, dst)
            if Path(src) == source:
                os.replace(replacement, source)

        monkeypatch.setattr(files.os, "link", replace_after_link)

    try:
        result = files.move(ctx, str(source), str(destination), files.revision(b"expected source"))
    except Fault as error:
        assert error.code == "stale_revision"
        assert error.details.get("verified") is not True
    else:
        assert result.get("verified") is not True

    assert source.read_bytes() == b"concurrent replacement"
    assert not destination.exists()


def test_move_retains_moved_bytes_when_source_is_recreated(ctx, tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"expected source")
    original_rename = files._rename_noreplace
    did_recreate = False

    def recreate_source_after_move(src, dst):
        nonlocal did_recreate
        original_rename(src, dst)
        if Path(src) == source and not did_recreate:
            source.write_bytes(b"new source")
            did_recreate = True

    monkeypatch.setattr(files, "_rename_noreplace", recreate_source_after_move)

    with pytest.raises(Fault) as error:
        files.move(ctx, str(source), str(destination), files.revision(b"expected source"))

    assert error.value.code == "stale_revision"
    assert source.read_bytes() == b"new source"
    assert destination.read_bytes() == b"expected source"
    assert error.value.details["retained_path"] == str(destination)


def test_move_reports_location_if_source_is_replaced_by_symlink(ctx, tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    target = tmp_path / "target.txt"
    source.write_bytes(b"expected source")
    target.write_bytes(b"concurrent target")
    original_rename = files._rename_noreplace

    def replace_source_with_symlink(src, dst):
        if Path(src) == source:
            source.unlink()
            source.symlink_to(target)
        return original_rename(src, dst)

    monkeypatch.setattr(files, "_rename_noreplace", replace_source_with_symlink)

    with pytest.raises(Fault) as error:
        files.move(ctx, str(source), str(destination), files.revision(b"expected source"))

    assert error.value.code == "stale_revision"
    assert error.value.details["retained_path"] == str(destination)
    assert destination.is_symlink()
    assert destination.readlink() == target
    assert target.read_bytes() == b"concurrent target"


def test_move_never_overwrites_existing_destination(ctx, tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"source")
    destination.write_bytes(b"destination")

    with pytest.raises(Fault) as error:
        files.move(ctx, str(source), str(destination), files.revision(b"source"))

    assert error.value.code == "conflict"
    assert source.read_bytes() == b"source"
    assert destination.read_bytes() == b"destination"


def test_move_refuses_same_path(ctx, tmp_path):
    source = tmp_path / "same.txt"
    source.write_bytes(b"source")

    with pytest.raises(Fault) as error:
        files.move(ctx, str(source), str(source), files.revision(b"source"))

    assert error.value.code == "invalid_params"
    assert source.read_bytes() == b"source"


def test_move_preserves_mode_and_returns_verified_undo(ctx, tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"source")
    source.chmod(0o640)

    receipt = files.move(ctx, str(source), str(destination), files.revision(b"source"))

    assert receipt["verified"] is True
    assert destination.read_bytes() == b"source"
    assert destination.stat().st_mode & 0o777 == 0o640
    assert not source.exists()
    undone = files.move(
        ctx,
        receipt["undo"]["params"]["source"],
        receipt["undo"]["params"]["destination"],
        receipt["undo"]["params"]["expected_revision"],
    )
    assert undone["verified"] is True
    assert source.read_bytes() == b"source"


def test_move_refuses_stale_source(ctx, tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"changed")

    with pytest.raises(Fault) as error:
        files.move(ctx, str(source), str(destination), files.revision(b"old"))

    assert error.value.code == "stale_revision"
    assert source.read_bytes() == b"changed"
    assert not destination.exists()
