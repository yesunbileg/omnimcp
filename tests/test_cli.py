import json
import tomllib
from pathlib import Path

import psutil
import pytest

import omnimcp
from omnimcp import cli
from omnimcp import hyprctl as hyprctl_mod

ROOT = Path(__file__).resolve().parent.parent


def test_version_sources_agree():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert omnimcp.__version__ == version
    skill = (ROOT / "skills" / "omnimcp" / "SKILL.md").read_text()
    assert f'version: "{version}"' in skill


def test_check_deps_reports_missing(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda t: None)
    ok, detail = cli._check_deps()
    assert not ok and "grim" in detail and "wtype" in detail


def test_doctor_never_crashes_on_broken_check(monkeypatch, capsys):
    def boom():
        raise RuntimeError("kaput")

    monkeypatch.setattr(cli, "CHECKS", (("broken", boom),))
    assert cli.doctor() == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out and "kaput" in out


def test_main_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "doctor", lambda: 0)
    monkeypatch.setattr(cli.sys, "argv", ["omnimcp", "doctor"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0

    monkeypatch.setattr(cli, "stop", lambda: 0)
    monkeypatch.setattr(cli.sys, "argv", ["omnimcp", "stop"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0

    monkeypatch.setattr(cli.sys, "argv", ["omnimcp", "bogus"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 2


def test_stop_no_beacon(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert cli.stop() == 0
    assert "no active OmniMCP session" in capsys.readouterr().out


def test_stop_signals_beacon_pid(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d = tmp_path / "omnimcp"
    d.mkdir()
    pid = cli.os.getpid()
    (d / "state.json").write_text(
        json.dumps({"pid": pid, "create_time": psutil.Process(pid).create_time(), "started": 1})
    )
    killed = []
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    assert cli.stop() == 0
    assert killed == [(pid, cli.signal.SIGTERM)]
    assert f"stopped OmniMCP (pid {pid})" in capsys.readouterr().out


def test_stop_handles_non_dict_beacon(tmp_path, monkeypatch, capsys):
    # valid JSON that is not an object must not crash the emergency stop
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d = tmp_path / "omnimcp"
    d.mkdir()
    (d / "state.json").write_text("[1, 2, 3]")
    assert cli.stop() == 1
    assert "unreadable" in capsys.readouterr().out


def test_stop_handles_dict_beacon_missing_pid(tmp_path, monkeypatch, capsys):
    # a dict beacon without a pid key hits the KeyError branch the fix added
    # (int({...}["pid"]) raises KeyError, must be caught)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d = tmp_path / "omnimcp"
    d.mkdir()
    (d / "state.json").write_text('{"started": 1}')
    assert cli.stop() == 1
    assert "unreadable" in capsys.readouterr().out


def test_stop_reaches_a_verb_acting_beside_a_server(tmp_path, monkeypatch, capsys):
    # a verb acting while a server owns the beacon is findable only through
    # the lock it holds; the panic bind must stop it too
    from omnimcp import verbs

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d = tmp_path / "omnimcp"
    d.mkdir()
    pid = cli.os.getpid()
    (d / "state.json").write_text(
        json.dumps({"pid": pid, "create_time": psutil.Process(pid).create_time(), "started": 1})
    )
    held = verbs._lock()  # this process stands in for the verb
    held.seek(0)
    held.truncate()
    held.write("7777")  # a pid that is not ours, so stop() may signal it
    held.flush()
    killed = []
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    try:
        assert cli._running_verb_pid() == 7777
        assert cli.stop() == 0
    finally:
        held.close()
    assert killed == [(7777, cli.signal.SIGTERM), (pid, cli.signal.SIGTERM)]
    out = capsys.readouterr().out
    assert "stopped a running OmniMCP verb (pid 7777)" in out
    assert f"stopped OmniMCP (pid {pid})" in out
    # lock released: nothing acting any more
    assert cli._running_verb_pid() is None


def test_a_verbs_beacon_is_not_removed_once_a_server_took_the_file(tmp_path, monkeypatch):
    from omnimcp import safety

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(safety, "_armed", True)  # keep atexit/signal out of the test process
    safety.init()
    beacon = safety.state_path()
    assert json.loads(beacon.read_text())["pid"] == cli.os.getpid()
    beacon.write_text(json.dumps({"pid": 4242, "started": 2}))  # a server started meanwhile
    safety.shutdown()
    assert json.loads(beacon.read_text())["pid"] == 4242
    safety.init()
    safety.shutdown()
    assert not beacon.exists()


def test_stop_clears_stale_beacon(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d = tmp_path / "omnimcp"
    d.mkdir()
    beacon = d / "state.json"
    beacon.write_text(json.dumps({"pid": 999999, "started": 1}))

    def gone(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(cli.os, "kill", gone)
    assert cli.stop() == 0
    assert "already gone" in capsys.readouterr().out
    assert not beacon.exists()


@pytest.mark.parametrize(
    "help_text, expect",
    [
        ("  -T <identifier> Set the identifier of a foreign toplevel", "even hidden or covered"),
        ("  -o <output> Set the output name to capture.", "crop the screen"),
    ],
)
def test_doctor_says_whether_grim_can_capture_a_window_itself(monkeypatch, help_text, expect):
    class Done:
        stdout, stderr = help_text, ""

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(hyprctl_mod, "query", lambda what: [{"stableId": "18000010"}])
    ok, detail = cli._window_capture_note()
    assert ok is True and expect in detail  # informational, never a failure


def test_doctor_needs_window_ids_from_hyprland_too(monkeypatch):
    # grim -T captures by the window id Hyprland reports from 0.54 on
    class Done:
        stdout, stderr = "  -T <identifier> Set the identifier", ""

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(hyprctl_mod, "query", lambda what: [{"address": "0xa"}])
    ok, detail = cli._window_capture_note()
    assert ok is True and "0.54" in detail and "crop the screen" in detail


def test_doctor_does_not_vouch_for_window_ids_it_could_not_see(monkeypatch):
    class Done:
        stdout, stderr = "  -T <identifier> Set the identifier", ""

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(hyprctl_mod, "query", lambda what: [])
    ok, detail = cli._window_capture_note()
    assert ok is True and "no window" in detail
