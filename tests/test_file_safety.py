"""Regular-file boundaries must not wait on special filesystem objects."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from omnimcp.adapters import files
from omnimcp.core.execution import Context
from omnimcp.core.registry import Fault
from omnimcp.core.state import Store


def test_read_rejects_fifo_without_waiting_for_a_writer(tmp_path):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    code = (
        "from omnimcp.adapters.files import read\n"
        "from omnimcp.core.registry import Fault\n"
        "import sys\n"
        "try:\n"
        "    read(None, sys.argv[1])\n"
        "except Fault as exc:\n"
        "    print(exc.code)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(fifo)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert result.stdout.strip() == "unsupported"


def test_current_rejects_fifo_without_waiting_for_a_writer(tmp_path):
    fifo = tmp_path / "input.fifo"
    os.mkfifo(fifo)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; "
            "from omnimcp.adapters.files import current; "
            "from omnimcp.core.registry import Fault\n"
            "try: current(Path(sys.argv[1]))\n"
            "except Fault as exc: print(exc.code)\n",
            str(fifo),
        ],
        capture_output=True,
        text=True,
        timeout=3,
        check=True,
    )
    assert result.stdout.strip() == "unsupported"


@pytest.mark.parametrize("operation", ["move", "undo"])
def test_post_rename_sync_failure_reports_actual_retained_bytes(tmp_path, monkeypatch, operation):
    store = Store(tmp_path / "state")
    ctx = Context(store)
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"fixture")
    receipt = None
    if operation == "undo":
        source.unlink()
        receipt = files.write(ctx, str(source), "fixture", "missing")

    def fail_sync(*paths):
        raise OSError("fixture directory sync failed")

    monkeypatch.setattr(files, "_fsync_dirs", fail_sync)
    try:
        with pytest.raises(Fault) as error:
            if operation == "move":
                files.move(ctx, str(source), str(destination), files.revision(b"fixture"))
            else:
                files.restore(ctx, str(source), receipt["backup"], receipt["revision"])
        assert error.value.code == "verification_failed"
        retained = Path(error.value.details["retained_path"])
        assert retained.read_bytes() == b"fixture"
        assert not source.exists()
    finally:
        store.close()


def test_post_unlink_sync_failure_does_not_claim_missing_quarantine_is_retained(
    tmp_path, monkeypatch
):
    store = Store(tmp_path / "state")
    ctx = Context(store)
    source = tmp_path / "created"
    receipt = files.write(ctx, str(source), "fixture", "missing")
    real_sync = files._fsync_dirs
    calls = 0

    def fail_second_sync(*paths):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fixture post-unlink sync failed")
        real_sync(*paths)

    monkeypatch.setattr(files, "_fsync_dirs", fail_second_sync)
    try:
        with pytest.raises(Fault) as error:
            files.restore(ctx, str(source), receipt["backup"], receipt["revision"])
        assert error.value.code == "verification_failed"
        assert error.value.details.get("removed") is True
        assert "retained_path" not in error.value.details
        assert not source.exists()
        assert list(tmp_path.glob(".created.undo-*")) == []
    finally:
        store.close()
