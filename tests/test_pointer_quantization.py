"""Pointer confinement checks the coordinates the default seat will receive."""

import pytest

from omnimcp import server


def test_pointer_click_refuses_rounding_across_adjacent_confined_window(monkeypatch):
    monitors = [
        {
            "id": 0,
            "name": "DP-1",
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080,
            "activeWorkspace": {"id": 1, "name": "1"},
            "specialWorkspace": {"id": 0, "name": ""},
        }
    ]
    clients = [
        {
            "address": "0x1",
            "class": "kitty",
            "workspace": {"id": 1, "name": "1"},
            "at": [0, 0],
            "size": [640, 800],
        },
        {
            "address": "0x2",
            "class": "firefox",
            "workspace": {"id": 1, "name": "1"},
            "at": [640, 0],
            "size": [800, 800],
        },
    ]
    delivered = []

    class DefaultSeatPointer:
        on_named_seat = False

        def click(self, *args, **kwargs):
            delivered.append((args, kwargs))

    def batch_query(commands):
        assert commands == ["monitors", "clients"]
        return [monitors, clients]

    def query(command):
        if command == "layers":
            return {}
        if command == "cursorpos":
            return {"x": 640, "y": 5}
        if command == "activewindow":
            return {"address": "0x1"}
        raise AssertionError(command)

    dispatches = []
    monkeypatch.setenv("OMNIMCP_BACKGROUND", "0")
    monkeypatch.setenv("OMNIMCP_CONFINE", "class:kitty")
    monkeypatch.setenv("OMNIMCP_AUTH_GUARD", "0")
    monkeypatch.setattr(server.safety, "touch", lambda *_: None)
    monkeypatch.setattr(server.hyprctl, "batch_query", batch_query)
    monkeypatch.setattr(server.hyprctl, "query", query)
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *args: dispatches.append(args))
    monkeypatch.setattr(server.hinput, "_with_pointer", lambda fn: fn(DefaultSeatPointer()))
    monkeypatch.setattr(server.hinput, "_vp", None)

    with pytest.raises(server.trust.TrustError, match="outside the confinement scope.*firefox"):
        server.pointer("click", x=639.6, y=5.0)

    assert dispatches == []
    assert delivered == []


def test_pointer_click_refuses_negative_rounding_across_adjacent_window(monkeypatch):
    monitors = [
        {
            "id": 0,
            "name": "DP-1",
            "x": -640,
            "y": 0,
            "width": 1920,
            "height": 1080,
            "activeWorkspace": {"id": 1, "name": "1"},
            "specialWorkspace": {"id": 0, "name": ""},
        }
    ]
    clients = [
        {
            "address": "0x1",
            "class": "kitty",
            "workspace": {"id": 1, "name": "1"},
            "at": [-640, 0],
            "size": [640, 800],
        },
        {
            "address": "0x2",
            "class": "firefox",
            "workspace": {"id": 1, "name": "1"},
            "at": [0, 0],
            "size": [800, 800],
        },
    ]
    delivered = []

    class DefaultSeatPointer:
        on_named_seat = False

        def click(self, *args, **kwargs):
            delivered.append((args, kwargs))

    monkeypatch.setenv("OMNIMCP_BACKGROUND", "0")
    monkeypatch.setenv("OMNIMCP_CONFINE", "class:kitty")
    monkeypatch.setenv("OMNIMCP_AUTH_GUARD", "0")
    monkeypatch.setattr(server.safety, "touch", lambda *_: None)
    monkeypatch.setattr(server.hyprctl, "batch_query", lambda commands: [monitors, clients])
    monkeypatch.setattr(
        server.hyprctl,
        "query",
        lambda command: (
            {}
            if command == "layers"
            else {"x": 0, "y": 5}
            if command == "cursorpos"
            else {"address": "0x1"}
            if command == "activewindow"
            else (_ for _ in ()).throw(AssertionError(command))
        ),
    )
    dispatches = []
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *args: dispatches.append(args))
    monkeypatch.setattr(server.hinput, "_with_pointer", lambda fn: fn(DefaultSeatPointer()))
    monkeypatch.setattr(server.hinput, "_vp", None)

    with pytest.raises(server.trust.TrustError, match="outside the confinement scope.*firefox"):
        server.pointer("click", x=-0.4, y=5.0)

    assert dispatches == []
    assert delivered == []


def test_default_seat_dry_run_does_not_create_virtual_pointer(monkeypatch):
    monkeypatch.setattr(server.hinput, "_vp", None)
    monkeypatch.setattr(
        server.hinput, "VirtualPointer", lambda: pytest.fail("dry run created a virtual pointer")
    )
    monkeypatch.setattr(server.safety, "touch", lambda *_: None)
    monkeypatch.setattr(server.trust, "guard_seat", lambda: None)
    monkeypatch.setattr(server.trust, "guard_allow_auth_override", lambda *_: None)
    monkeypatch.setattr(server, "_pointer_policy", lambda *args: None)
    monkeypatch.setattr(server.journal, "dry_run", lambda: True)

    server.pointer("move", x=12.4, y=7.6)

    assert server.hinput._vp is None
