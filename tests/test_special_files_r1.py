"""The file reader accepts regular files and rejects other filesystem objects."""

import os
import socket

import pytest

from omnimcp.adapters import files
from omnimcp.core.registry import Fault


def test_read_rejects_symlink_without_reading_its_target(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("secret")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    with pytest.raises(Fault) as error:
        files.read(None, str(link))

    assert error.value.code == "invalid_params"


def test_read_rejects_symlink_swapped_in_after_path_check(tmp_path, monkeypatch):
    path = tmp_path / "file.txt"
    path.write_text("original")
    target = tmp_path / "target.txt"
    target.write_text("secret")
    open_file = os.open

    def swap_then_open(candidate, flags, *args, **kwargs):
        if os.fspath(candidate) == str(path):
            path.unlink()
            path.symlink_to(target)
        return open_file(candidate, flags, *args, **kwargs)

    monkeypatch.setattr(files.os, "open", swap_then_open)
    with pytest.raises(Fault) as error:
        files.read(None, str(path))

    assert error.value.code == "invalid_params"


def test_read_rejects_socket_swapped_in_before_open(tmp_path, monkeypatch):
    path = tmp_path / "file.txt"
    path.write_text("original")
    endpoint = socket.socket(socket.AF_UNIX)
    open_file = os.open

    def swap_then_open(candidate, flags, *args, **kwargs):
        if os.fspath(candidate) == str(path):
            path.unlink()
            endpoint.bind(str(path))
        return open_file(candidate, flags, *args, **kwargs)

    monkeypatch.setattr(files.os, "open", swap_then_open)
    try:
        with pytest.raises(Fault) as error:
            files.read(None, str(path))
        assert error.value.code == "unsupported"
    finally:
        endpoint.close()


def test_read_reports_disappearance_before_open_as_stale(tmp_path, monkeypatch):
    path = tmp_path / "file.txt"
    path.write_text("original")
    open_file = os.open

    def disappear_then_open(candidate, flags, *args, **kwargs):
        if os.fspath(candidate) == str(path):
            path.unlink()
        return open_file(candidate, flags, *args, **kwargs)

    monkeypatch.setattr(files.os, "open", disappear_then_open)
    with pytest.raises(Fault) as error:
        files.read(None, str(path))
    assert error.value.code == "stale_revision"


def test_read_reports_disappearance_after_open_as_stale(tmp_path, monkeypatch):
    path = tmp_path / "file.txt"
    path.write_text("original")
    real_stat = type(path).stat
    path_stat_calls = 0

    def disappear_on_final_stat(candidate, *args, **kwargs):
        nonlocal path_stat_calls
        if candidate == path and kwargs.get("follow_symlinks", True):
            path_stat_calls += 1
            if path_stat_calls == 2:
                path.unlink()
        return real_stat(candidate, *args, **kwargs)

    monkeypatch.setattr(type(path), "stat", disappear_on_final_stat)
    with pytest.raises(Fault) as error:
        files.read(None, str(path))
    assert error.value.code == "stale_revision"


@pytest.mark.parametrize("special_path", ["/dev/null"])
def test_read_rejects_device_nodes(tmp_path, special_path):
    with pytest.raises(Fault) as error:
        files.read(None, special_path)

    assert error.value.code == "unsupported"


def test_read_rejects_unix_socket(tmp_path):
    socket_path = tmp_path / "endpoint.sock"
    endpoint = socket.socket(socket.AF_UNIX)
    try:
        endpoint.bind(str(socket_path))
        with pytest.raises(Fault) as error:
            files.read(None, str(socket_path))
        assert error.value.code == "unsupported"
    finally:
        endpoint.close()
