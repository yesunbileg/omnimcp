"""Opt-in launch allowlist policy. These tests must never reach a desktop."""

import pytest

from omnimcp import server


def _allowlist(tmp_path, entries, monkeypatch, mode=0o600):
    path = tmp_path / "launch-allowlist.txt"
    path.write_text("\n".join(entries) + "\n")
    path.chmod(mode)
    monkeypatch.setenv("OMNIMCP_LAUNCH_ALLOW", str(path))
    return path


def test_allowlist_unset_preserves_existing_command_behavior(no_real_desktop, monkeypatch):
    monkeypatch.delenv("OMNIMCP_LAUNCH_ALLOW", raising=False)
    server._check_launch_allowed("arbitrary app --flag")


@pytest.mark.parametrize("command", ["firefox"])
def test_allowlist_accepts_exact_bare_entry(no_real_desktop, monkeypatch, tmp_path, command):
    _allowlist(tmp_path, ["firefox"], monkeypatch)
    server._check_launch_allowed(command)


def test_allowlist_allows_quoted_operators_as_arguments(no_real_desktop, monkeypatch, tmp_path):
    _allowlist(tmp_path, ["firefox"], monkeypatch)
    server._check_launch_allowed('firefox "one;two" \'three|four\'')


def test_allowlist_is_reread_on_each_decision(no_real_desktop, monkeypatch, tmp_path):
    path = _allowlist(tmp_path, ["first"], monkeypatch)
    server._check_launch_allowed("first")
    path.write_text("second\n")
    with pytest.raises(server.LaunchNotAllowedError):
        server._check_launch_allowed("first")


def test_allowlist_accepts_absolute_entry_only_for_exact_path(
    no_real_desktop, monkeypatch, tmp_path
):
    _allowlist(tmp_path, ["/opt/apps/browser"], monkeypatch)
    server._check_launch_allowed("/opt/apps/browser --new-window")
    with pytest.raises(server.LaunchNotAllowedError) as error:
        server._check_launch_allowed("/usr/bin/browser")
    assert error.value.code == "launch_not_allowed"


@pytest.mark.parametrize("command", [
    "bad;true", "bad & true", "bad | true", "bad > /tmp/out", "bad < /tmp/in",
    "bad\ntrue", "bad `id`", "bad $(id)", "bad ${HOME}", "bad '\u0060id\u0060'",
    "bad '$(id)'", "bad '${HOME}'",
])
def test_allowlist_rejects_shell_syntax(no_real_desktop, monkeypatch, tmp_path, command):
    _allowlist(tmp_path, ["bad"], monkeypatch)
    with pytest.raises(server.LaunchNotAllowedError) as error:
        server._check_launch_allowed(command)
    assert error.value.code == "launch_not_allowed"


def test_allowlist_rejects_untrusted_file_permissions(no_real_desktop, monkeypatch, tmp_path):
    _allowlist(tmp_path, ["good"], monkeypatch, mode=0o622)
    with pytest.raises(server.LaunchNotAllowedError):
        server._check_launch_allowed("good")


def test_fifo_allowlist_is_refused_without_blocking(tmp_path):
    import os
    import subprocess
    import sys

    path = tmp_path / "allowlist.fifo"
    os.mkfifo(path)
    env = {**os.environ, "OMNIMCP_LAUNCH_ALLOW": str(path)}
    result = subprocess.run(
        [sys.executable, "-c", (
            "from omnimcp.server import _check_launch_allowed, LaunchNotAllowedError\n"
            "try:\n _check_launch_allowed('app')\n"
            "except LaunchNotAllowedError:\n pass\n"
            "else:\n raise AssertionError('FIFO accepted')\n"
        )], env=env, capture_output=True, text=True, timeout=2,
    )
    assert result.returncode == 0, result.stderr


def test_launch_policy_runs_before_dry_run(no_real_desktop, monkeypatch, tmp_path):
    _allowlist(tmp_path, ["allowed"], monkeypatch)
    with pytest.raises(server.LaunchNotAllowedError) as error:
        server.launch("denied")
    assert error.value.code == "launch_not_allowed"


def test_launch_rejects_unsafe_workspace_before_desktop(no_real_desktop, monkeypatch):
    monkeypatch.delenv("OMNIMCP_LAUNCH_ALLOW", raising=False)
    with pytest.raises(ValueError, match="is not a workspace"):
        server.launch("app", workspace="name:bad value")


def test_rejects_newline_even_in_quotes(no_real_desktop, monkeypatch, tmp_path):
    _allowlist(tmp_path, ["app"], monkeypatch)
    with pytest.raises(server.LaunchNotAllowedError):
        server._check_launch_allowed('app "one\ntwo"')


@pytest.mark.parametrize("command", ['app "a & b"', "app 'a & b'"])
def test_allows_quoted_ampersand(no_real_desktop, monkeypatch, tmp_path, command):
    _allowlist(tmp_path, ["app"], monkeypatch)
    server._check_launch_allowed(command)


@pytest.mark.parametrize(
    "command", ["app; other", "app && other", "app | other", "app > f", 'app "$(other)"']
)
def test_rejects_requested_shell_syntax(no_real_desktop, monkeypatch, tmp_path, command):
    _allowlist(tmp_path, ["app"], monkeypatch)
    with pytest.raises(server.LaunchNotAllowedError):
        server._check_launch_allowed(command)



def test_automatic_workspace_validation(no_real_desktop):
    with pytest.raises(ValueError, match="is not a workspace"):
        server._validate_launch_workspace("name:bad value")
    server._validate_launch_workspace("name:notes")
    server._validate_launch_workspace("99")


@pytest.mark.parametrize("entry,command,allowed", [
    ("firefox", "firefox", True), ("firefox", "/tmp/x/firefox", False),
    ("firefox", "./firefox", False), ("firefox", "bin/firefox", False),
    ("firefox", "FIREFOX", False), ("/usr/bin/firefox", "/usr/bin/firefox", True),
    ("/usr/bin/firefox", "firefox", False),
    ("/usr/bin/firefox", "/usr/bin/../bin/firefox", False),
    ("/usr/bin/firefox", "/usr/bin//firefox", False), ("bin/firefox", "bin/firefox", False),
])
def test_allowlist_matches_exact_executable(
    no_real_desktop, monkeypatch, tmp_path, entry, command, allowed
):
    _allowlist(tmp_path, [entry], monkeypatch)
    if allowed:
        server._check_launch_allowed(command)
    else:
        with pytest.raises(server.LaunchNotAllowedError):
            server._check_launch_allowed(command)


@pytest.mark.parametrize("kind", ["relative", "missing", "directory", "symlink", "owner",
                                  "group", "world", "empty_var", "empty", "comments"])
def test_allowlist_file_must_be_trusted(no_real_desktop, monkeypatch, tmp_path, kind):
    path = _allowlist(tmp_path, ["firefox"], monkeypatch)
    if kind == "relative":
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OMNIMCP_LAUNCH_ALLOW", path.name)
    elif kind == "missing":
        path.unlink()
    elif kind == "directory":
        monkeypatch.setenv("OMNIMCP_LAUNCH_ALLOW", str(tmp_path))
    elif kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        monkeypatch.setenv("OMNIMCP_LAUNCH_ALLOW", str(link))
    elif kind == "owner":
        monkeypatch.setattr(server.os, "getuid", lambda: path.stat().st_uid + 1)
    elif kind == "group":
        path.chmod(0o620)
    elif kind == "world":
        path.chmod(0o602)
    elif kind == "empty_var":
        monkeypatch.setenv("OMNIMCP_LAUNCH_ALLOW", "")
    elif kind == "empty":
        path.write_text("")
    elif kind == "comments":
        path.write_text("# firefox\n  # firefox\n")
    with pytest.raises(server.LaunchNotAllowedError) as error:
        server._check_launch_allowed("firefox")
    assert error.value.code == "launch_not_allowed"


@pytest.mark.parametrize("char", [chr(i) for i in list(range(9)) + list(range(10, 32))
                                  + list(range(127, 160))])
def test_allowlist_rejects_control_characters(no_real_desktop, monkeypatch, tmp_path, char):
    _allowlist(tmp_path, ["x"], monkeypatch)
    with pytest.raises(server.LaunchNotAllowedError):
        server._check_launch_allowed("x " + char + "y")


@pytest.mark.parametrize("command,allowed", [
    (r"x \; y", True), ("x |& y", False), ("x >| y", False),
    ("x 2>&1", False), ("x <<EOF", False), ("x &", False),
    ("x (y)", True), ("(x)", False), ("x $'a;b'", False),
    (r"x $'\'; y; \''", False), ("x # y", True), ("x\ty", True),
    ("x ~/y", True), ("x $HOME", True), ("x *", True),
])
def test_allowlist_scanner_cases(no_real_desktop, monkeypatch, tmp_path, command, allowed):
    _allowlist(tmp_path, ["x"], monkeypatch)
    if allowed:
        server._check_launch_allowed(command)
    else:
        with pytest.raises(server.LaunchNotAllowedError):
            server._check_launch_allowed(command)


def test_scanner_differential_against_posix_shell(monkeypatch, tmp_path):
    import os
    import random
    import shlex
    import subprocess
    import time

    _allowlist(tmp_path, ["x"], monkeypatch)
    empty = tmp_path / "empty"
    empty.mkdir()
    alphabet = "abcxy01 \t\r\"'\\;&|<>()!=%,./-"
    randomizer = random.Random(1906)
    accepted = refused = 0
    start = time.monotonic()
    for _ in range(2000):
        sample = "".join(randomizer.choice(alphabet) for _ in range(randomizer.randrange(25)))
        try:
            server._check_launch_allowed("x " + sample)
        except server.LaunchNotAllowedError:
            continue
        accepted += 1
        result = subprocess.run(
            ["/usr/bin/timeout", "5", "/bin/sh", "-c",
             "set -- " + sample + " ; printf '%s\\0' \"$@\""],
            cwd=empty, env={"PATH": "/nonexistent", "HOME": str(empty)},
            capture_output=True, timeout=6, check=False,
        )
        if result.returncode:
            assert result.returncode != 124 and not result.stdout
            assert b"syntax error" in result.stderr.lower()
            refused += 1
        else:
            words = shlex.split(sample)
            expected = b"".join(os.fsencode(word) + b"\0" for word in (words or [""]))
            assert result.stdout == expected, repr(sample)
    elapsed = time.monotonic() - start
    print(f"differential: {accepted} accepted, {refused} shell refuses, {elapsed:.2f}s")
    assert elapsed < 30
