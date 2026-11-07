import pytest

from omnimcp import hyprctl, server


def test_wait_for_close_already_gone(monkeypatch):
    # no client matches -> already closed, returns without touching the socket
    def _no_connect():
        raise AssertionError("should not connect when already satisfied")

    monkeypatch.setattr(hyprctl, "query", lambda cmd: [] if cmd == "clients" else {})
    monkeypatch.setattr(server.events, "EventStream", _no_connect)
    out = server.wait_for("window_close", match="0xdead")
    assert out["already"] is True


def test_wait_for_close_still_open_waits(monkeypatch):
    monkeypatch.setattr(
        hyprctl, "query", lambda cmd: [{"address": "0xabc", "class": "kitty", "title": "x"}]
    )

    class S:
        def wait_for(self, names, matcher, timeout):
            return ("closewindow", {"address": "0xabc"})

        def __enter__(self):
            return self

        def __exit__(self, *e):
            pass

    monkeypatch.setattr(server.events, "EventStream", lambda: S())
    out = server.wait_for("window_close", match="0xabc")
    assert out["event"] == "closewindow" and "already" not in out


def test_wait_for_workspace_already_active(monkeypatch):
    def _no_connect():
        raise AssertionError("should not connect when already satisfied")

    monkeypatch.setattr(hyprctl, "query", lambda cmd: {"name": "3"})
    monkeypatch.setattr(server.events, "EventStream", _no_connect)
    out = server.wait_for("workspace", match="3")
    assert out["already"] is True and out["name"] == "3"


def test_hypr_focus_window_refused_out_of_scope(monkeypatch):
    # integration: hypr's guard_window(target) call site is real; focusing
    # an out-of-scope window by address is refused before dispatch
    monkeypatch.setenv("OMNIMCP_CONFINE", "class:kitty")
    monkeypatch.setattr(server.safety, "touch", lambda *a: None)
    firefox = {
        "address": "0xff",
        "class": "firefox",
        "workspace": {"id": 1},
        "at": [0, 0],
        "size": [10, 10],
        "mapped": True,
    }
    dispatched = []
    monkeypatch.setattr(server.hyprctl, "query", lambda cmd: [firefox])
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *a: dispatched.append(a))
    with pytest.raises(server.trust.TrustError, match="confinement scope"):
        server.hypr("focus_window", target="0xff")
    assert dispatched == []
