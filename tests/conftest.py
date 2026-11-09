"""Shared test wiring.

The one rule here: a unit test must never read live system state. The
0.9.3 audit found a guard that was dead code against the real
compositor while its tests passed happily on fabricated fixtures, so
anything that touches the machine gets neutralized by default and a
test that wants the interesting state opts in explicitly.
"""

import pytest

from omnimcp import a11y, dbuswire, hyprctl, journal, server, trust


@pytest.fixture(autouse=True)
def no_ambient_journal(monkeypatch):
    """No recording, no dry run, unless a test asks for it.

    Same rule as below, pointed at the developer's environment rather
    than the machine's: a suite run with OMNIMCP_JOURNAL exported would
    append hundreds of fabricated entries to a real audit trail, and one
    with OMNIMCP_DRYRUN set would pass while every acting tool did
    nothing.
    """
    for var in ("OMNIMCP_JOURNAL", "OMNIMCP_JOURNAL_TEXT", "OMNIMCP_DRYRUN"):
        monkeypatch.delenv(var, raising=False)
    journal._broken = False
    # replay marks its records `by: replay` and the CLI verbs stamp theirs
    # with a source; a test that ran either must not leave the mark on every
    # record the next test writes
    monkeypatch.setattr(journal, "_origin", "")
    monkeypatch.setattr(journal, "_source", "")
    # and a verb switches the content blocks to the plain kind for the rest
    # of the process; the MCP-facing tests must keep seeing the real types
    monkeypatch.setattr(server, "_plain_blocks", False)


@pytest.fixture(autouse=True)
def hyprlang_provider(monkeypatch):
    """The config manager is hyprlang, unless a test says otherwise.

    Same rule again: hyprctl.provider() shells out to the compositor and
    then caches the answer in a module global, so without this the suite
    would probe the developer's own session and whichever test got there
    first would decide the wire format for every test after it.
    """
    monkeypatch.setattr(hyprctl, "_provider", hyprctl.HYPRLANG)


@pytest.fixture(autouse=True)
def unlocked_session(monkeypatch):
    """No session locker, unless a test says otherwise.

    trust.session_locked() scans /proc, so without this the suite's
    result would depend on whether the machine running it happens to be
    locked: green on a developer's desk, red in a locked session.
    """
    monkeypatch.setattr(trust, "session_locked", lambda: None)


@pytest.fixture(autouse=True)
def compositor_lock_unknown(monkeypatch):
    """The compositor cannot be asked about the lock, unless a test says
    otherwise, so trust.session_locked() falls back to its /proc scan.

    Asking would run `hyprctl locked` against whatever Hyprland happens
    to be running the suite.
    """
    monkeypatch.setattr(trust, "_compositor_locked", lambda: None)


@pytest.fixture(autouse=True)
def foreground_by_default(monkeypatch):
    """OMNIMCP_BACKGROUND=0 (0.12 behaviour) unless a test says otherwise.

    The tests written before background mode assert foreground behaviour;
    background tests unset it to get the automatic default.
    """
    monkeypatch.setenv("OMNIMCP_BACKGROUND", "0")
    # and the documented defaults for the agent's workspaces, whatever the
    # developer's shell exports
    monkeypatch.delenv("OMNIMCP_AGENT_WORKSPACES", raising=False)
    monkeypatch.delenv("OMNIMCP_AGENT_FILL", raising=False)
    monkeypatch.delenv("OMNIMCP_CONFINE", raising=False)


@pytest.fixture(autouse=True)
def no_live_batch_query(monkeypatch):
    """hyprctl.batch_query and hyprctl.query fail unless a test stubs them.

    Same rule: it shells out to whatever Hyprland is running the suite, and
    a test that forgot to stub it would pass or fail on the developer's own
    desktop. Code that degrades without the compositor gets to degrade.
    """

    def unreachable(cmds):
        raise hyprctl.HyprctlError("no compositor in unit tests")

    monkeypatch.setattr(hyprctl, "batch_query", unreachable)
    monkeypatch.setattr(hyprctl, "query", lambda what: unreachable([what]))


@pytest.fixture(autouse=True)
def no_live_accessibility(monkeypatch):
    """a11y.connect() fails unless a test stubs it, and no D-Bus socket
    opens through the shared connection.

    Same rule: on a developer's desktop the accessibility bus carries
    their open apps, a chat app's messages included, and a test that
    reached it would read, or press, whatever is open there.
    """

    def no_bus():
        raise a11y.A11yError("no accessibility bus in unit tests")

    def no_socket(address):
        raise dbuswire.Unreachable("no D-Bus sockets in unit tests")

    monkeypatch.setattr(a11y, "connect", no_bus)
    monkeypatch.setattr(dbuswire, "connection", no_socket)


@pytest.fixture
def no_real_desktop(monkeypatch, no_ambient_journal, no_live_batch_query, no_live_accessibility):
    """Fail loudly at every desktop/process boundary in isolated in-process tests."""
    import os
    import socket
    import subprocess

    from omnimcp import input as hinput
    from omnimcp import wire

    def forbidden(*args, **kwargs):
        pytest.fail("real desktop or process boundary reached", pytrace=False)

    for name in (
        "HYPRLAND_INSTANCE_SIGNATURE",
        "WAYLAND_DISPLAY",
        "DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OMNIMCP_DRYRUN", "1")
    for name in ("run", "Popen", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    for name in dir(os):
        if name.startswith("exec") or name in ("posix_spawn", "posix_spawnp"):
            monkeypatch.setattr(os, name, forbidden)
    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    for name in ("_run", "query", "batch_query", "dispatch", "eval_lua"):
        monkeypatch.setattr(hyprctl, name, forbidden)
    monkeypatch.setattr(a11y, "connect", forbidden)
    monkeypatch.setattr(dbuswire, "connection", forbidden)
    monkeypatch.setattr(dbuswire, "Connection", forbidden)
    monkeypatch.setattr(wire, "VirtualPointer", forbidden)
    monkeypatch.setattr(wire, "VirtualKeyboard", forbidden)
    monkeypatch.setattr(hinput, "VirtualPointer", forbidden)
    monkeypatch.setattr(hinput, "VirtualKeyboard", forbidden)
    monkeypatch.setattr(hinput, "_with_pointer", forbidden)
    monkeypatch.setattr(hinput, "_with_keyboard", forbidden)
