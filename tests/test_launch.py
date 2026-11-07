"""launch() behaviour around single-instance apps and slow startups.

Regression source: real test session 2026-07-16, `google-chrome
--profile-picker` with workspace=2 opened its window from the existing
Chrome process on workspace 5, and the old 3s detection window missed it
entirely.
"""

import itertools

import pytest

from omnimcp import server


class FakeHyprctl:
    def __init__(self, snapshots):
        self._snapshots = snapshots  # list of client lists, consumed per query
        self.dispatched = []

    def query(self, cmd):
        assert cmd == "clients"
        return self._snapshots[0] if len(self._snapshots) == 1 else self._snapshots.pop(0)

    def dispatch(self, *args):
        self.dispatched.append(args)


EXISTING = {"address": "0xa", "class": "kitty", "title": "~", "workspace": {"id": 5, "name": "5"}}
CHROME = {
    "address": "0xb",
    "class": "google-chrome",
    "title": "profile picker",
    "workspace": {"id": 5, "name": "5"},
}


class NoSocket:
    def __init__(self):
        raise server.events.EventError("no socket in tests")


class FakeStream:
    """Event-socket double: yields one openwindow event."""

    def __init__(self, payload):
        self._payload = payload

    def wait_for(self, names, matcher, timeout):
        assert "openwindow" in names
        event = ("openwindow", self._payload) if self._payload else None
        return event if event and (matcher is None or matcher(*event)) else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda s: None)


def _patch(monkeypatch, fake, stream="none"):
    monkeypatch.setattr(server.hyprctl, "query", fake.query)
    monkeypatch.setattr(server.hyprctl, "dispatch", fake.dispatch)
    if stream == "none":
        monkeypatch.setattr(server.events, "EventStream", NoSocket)
    else:
        monkeypatch.setattr(server.events, "EventStream", lambda: stream)


def test_launch_does_not_claim_off_workspace_single_instance_window(monkeypatch, no_sleep):
    """A same-class window on the human's workspace does not prove launch provenance."""
    fake = FakeHyprctl([[EXISTING], [EXISTING], [EXISTING, CHROME]])
    _patch(monkeypatch, fake)
    owned = set()
    monkeypatch.setattr(server.trust, "note_launched", lambda address, cls: owned.add(address))
    out = server.launch("google-chrome", workspace="2", wait_s=1)
    assert isinstance(out, str)
    assert "couldn't safely associate" in out
    assert fake.dispatched == [("exec", "[workspace 2 silent] google-chrome")]
    assert owned == set()


def test_launch_no_move_when_rule_worked(monkeypatch, no_sleep):
    landed_right = dict(CHROME, workspace={"id": 2, "name": "2"})
    fake = FakeHyprctl([[EXISTING], [EXISTING, landed_right]])
    _patch(monkeypatch, fake)
    out = server.launch("google-chrome", workspace="2")
    assert out["workspace"] == 2
    assert "note" not in out
    assert not any(d[0] == "movetoworkspacesilent" for d in fake.dispatched)


def test_launch_timeout_message_mentions_single_instance(monkeypatch, no_sleep):
    fake = FakeHyprctl([[EXISTING]])  # nothing ever appears
    _patch(monkeypatch, fake)
    clock = itertools.count(start=0, step=3.0)
    monkeypatch.setattr(server.time, "monotonic", lambda: next(clock))
    out = server.launch("slowapp", workspace="2", wait_s=8)
    assert isinstance(out, str)
    assert "single-instance" in out
    assert "desktop()" in out


def test_launch_wait_s_clamped(monkeypatch, no_sleep):
    fake = FakeHyprctl([[EXISTING], [EXISTING, CHROME]])
    _patch(monkeypatch, fake)
    out = server.launch("app", wait_s=999)  # must not loop for 999s
    assert out["address"] == "0xb"


def test_launch_uses_event_socket_when_available(monkeypatch, no_sleep):
    fake = FakeHyprctl([[EXISTING], [EXISTING, CHROME]])
    stream = FakeStream({"address": "0xb", "workspace": "5", "class": "google-chrome"})
    _patch(monkeypatch, fake, stream=stream)
    owned = set()
    monkeypatch.setattr(server.trust, "note_launched", lambda address, cls: owned.add(address))
    out = server.launch("google-chrome", workspace="2", wait_s=1)
    assert isinstance(out, str)
    assert "couldn't safely associate" in out
    assert fake.dispatched == [("exec", "[workspace 2 silent] google-chrome")]
    assert owned == set()


def test_launch_refuses_wrong_class_even_on_requested_workspace(monkeypatch, no_sleep):
    kitty = {"address": "0xc", "class": "kitty", "title": "human terminal",
             "workspace": {"id": 2, "name": "2"}}
    fake = FakeHyprctl([[EXISTING], [EXISTING, kitty]])
    _patch(monkeypatch, fake)
    owned = set()
    monkeypatch.setattr(server.trust, "note_launched", lambda address, cls: owned.add(address))

    out = server.launch("foot", workspace="2", wait_s=1)

    assert isinstance(out, str) and "couldn't safely associate" in out
    assert fake.dispatched == [("exec", "[workspace 2 silent] foot")]
    assert owned == set()


def test_launch_polling_keeps_waiting_when_event_client_is_not_ready(monkeypatch, no_sleep):
    fake = FakeHyprctl([[EXISTING], [EXISTING], [EXISTING], [EXISTING, dict(
        CHROME, workspace={"id": 2, "name": "2"}
    )]])
    stream = FakeStream({"address": "0xb", "workspace": "2", "class": "google-chrome"})
    _patch(monkeypatch, fake, stream=stream)

    out = server.launch("google-chrome", workspace="2", wait_s=1)

    assert out["address"] == "0xb"
    assert out["workspace"] == 2


def test_launch_resolves_workspace_name_event_after_client_appears(monkeypatch):
    """An unresolved event remains a candidate while the client list catches up."""
    elapsed = [0.0]
    ready = [False]
    candidate = dict(CHROME, workspace={"id": 2, "name": "work"})
    client_queries = [0]

    def query(cmd):
        assert cmd == "clients"
        client_queries[0] += 1
        if ready[0] and client_queries[0] >= 4:
            return [candidate]
        return []

    class DelayedClientStream(FakeStream):
        def wait_for(self, names, matcher, timeout):
            event = ("openwindow", {
                "address": "0xb", "workspace": "work", "class": "google-chrome",
            })
            if matcher(*event):
                # The event arrived before clients exposed its workspace id.
                elapsed[0] += 0.05
                return event
            # EventStream keeps looking until its deadline after a rejection.
            elapsed[0] += timeout
            ready[0] = True
            return None

    monkeypatch.setenv("OMNIMCP_BACKGROUND", "0")
    monkeypatch.setattr(server.safety, "touch", lambda *_: None)
    monkeypatch.setattr(server.hyprctl, "query", query)
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *args: None)
    monkeypatch.setattr(server.events, "EventStream", lambda: DelayedClientStream(None))
    monkeypatch.setattr(server.time, "monotonic", lambda: elapsed[0])

    def advance(duration):
        elapsed[0] += duration
        if elapsed[0] >= 0.2:
            ready[0] = True

    monkeypatch.setattr(server.time, "sleep", advance)
    monkeypatch.setattr(server, "_active_address", lambda: None)
    owned = []
    monkeypatch.setattr(server.trust, "note_launched", lambda address, cls: owned.append(address))

    out = server.launch("google-chrome", workspace="2", wait_s=1)

    assert isinstance(out, dict), (out, elapsed, client_queries)
    assert out["address"] == "0xb"
    assert out["workspace"] == 2
    assert owned == ["0xb"]
    assert elapsed[0] == pytest.approx(0.2)


def test_launch_polling_does_not_accept_a_window_after_deadline(monkeypatch):
    elapsed = [0.0]
    client = dict(CHROME, workspace={"id": 2, "name": "2"})

    def late_sleep(_duration):
        elapsed[0] += 0.25

    monkeypatch.setattr(server.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(server.time, "sleep", late_sleep)
    monkeypatch.setattr(server.hyprctl, "query", lambda cmd: [client])

    assert server._await_new_window(set(), 0.2) is None


def test_launch_polling_does_not_accept_after_slow_matcher(monkeypatch):
    elapsed = [0.0]
    client = dict(CHROME, workspace={"id": 2, "name": "2"})
    monkeypatch.setattr(server.time, "monotonic", lambda: elapsed[0])

    def advance(duration):
        elapsed[0] += duration

    monkeypatch.setattr(server.time, "sleep", advance)
    monkeypatch.setattr(server.hyprctl, "query", lambda cmd: [client])

    def slow_accept(_client):
        elapsed[0] += 0.1
        return True

    assert server._await_new_window(set(), 0.2, slow_accept) is None


def test_launch_does_not_claim_client_lookup_returned_after_deadline(monkeypatch):
    elapsed = [0.0]
    candidate = dict(CHROME, **{
        "class": "foot", "workspace": {"id": 2, "name": "2"},
    })
    client_queries = [0]
    owned = []

    def query(cmd):
        assert cmd == "clients"
        client_queries[0] += 1
        if client_queries[0] == 1:
            return []
        elapsed[0] = 1.1
        return [candidate]

    monkeypatch.setenv("OMNIMCP_BACKGROUND", "0")
    monkeypatch.setattr(server.safety, "touch", lambda *_: None)
    monkeypatch.setattr(server.hyprctl, "query", query)
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *args: None)
    monkeypatch.setattr(server.events, "EventStream", lambda: FakeStream({
        "address": "0xb", "workspace": "2", "class": "foot",
    }))
    monkeypatch.setattr(server.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(server, "_active_address", lambda: None)
    monkeypatch.setattr(server.trust, "note_launched", lambda address, cls: owned.append(address))

    result = server.launch("foot", workspace="2", wait_s=1)

    assert isinstance(result, str) and "no new window appeared" in result
    assert owned == []


def test_visible_special_workspace_event_reports_guarantee_focus_risk(monkeypatch, no_sleep):
    monkeypatch.setenv("OMNIMCP_BACKGROUND", "1")
    candidate = {"address": "0xc", "class": "foot", "title": "", "workspace": {
        "id": -99, "name": "special:notes"
    }}
    calls = {"clients": 0}

    def query(cmd):
        if cmd == "clients":
            calls["clients"] += 1
            return [] if calls["clients"] == 1 else [candidate]
        if cmd == "monitors":
            return [{"activeWorkspace": {"id": 1, "name": "1"},
                     "specialWorkspace": {"id": -99, "name": "special:notes"}}]
        if cmd == "activewindow":
            return {"address": "0xa"}
        raise AssertionError(cmd)

    stream = FakeStream({"address": "0xc", "workspace": "special:notes", "class": "foot"})
    monkeypatch.setattr(server.hyprctl, "query", query)
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *args: None)
    monkeypatch.setattr(server.events, "EventStream", lambda: stream)
    monkeypatch.setattr(server, "_active_address", lambda: "0xa")
    monkeypatch.setattr(server.trust, "note_launched", lambda *args: None)

    out = server.launch("foot", workspace="99", wait_s=1)

    assert isinstance(out, str) and "OMNIMCP_BACKGROUND" in out
    assert "may have taken the human's focus" in out


def test_event_launch_snapshots_clients_after_subscribing_before_dispatch(monkeypatch):
    order = []

    class Stream:
        def __init__(self):
            order.append("subscribe")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def wait_for(self, names, matcher, timeout):
            order.append("wait")
            return None

    monkeypatch.setattr(server.events, "EventStream", Stream)
    monkeypatch.setattr(server.hyprctl, "query", lambda cmd: order.append("clients") or [])
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *args: order.append("dispatch"))
    monkeypatch.setattr(server, "_await_new_window", lambda *args, **kwargs: None)

    server._launch_and_wait("foot", 1)

    assert order[:3] == ["subscribe", "clients", "dispatch"]


def test_launch_event_timeout_message(monkeypatch, no_sleep):
    fake = FakeHyprctl([[EXISTING]])
    _patch(monkeypatch, fake, stream=FakeStream(None))
    out = server.launch("slowapp", wait_s=2)
    assert isinstance(out, str) and "no new window" in out


def test_launch_ignores_queued_event_for_client_in_predispatch_snapshot(monkeypatch):
    stale = dict(CHROME, workspace={"id": 2, "name": "2"})
    queried = iter([[stale], [stale]])
    monkeypatch.setattr(server.hyprctl, "query", lambda cmd: next(queried))
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *args: None)
    stream = FakeStream({"address": "0xb", "workspace": "2", "class": "google-chrome"})
    monkeypatch.setattr(server.events, "EventStream", lambda: stream)
    monkeypatch.setattr(server, "_await_new_window", lambda *args, **kwargs: None)

    result = server._launch_and_wait("google-chrome", 1, lambda payload: True)

    assert result is None


def test_launch_event_rechecks_resolved_client_class(monkeypatch, no_sleep):
    kitty = {"address": "0xc", "class": "kitty", "title": "human terminal",
             "workspace": {"id": 2, "name": "2"}}
    stream = FakeStream({"address": "0xc", "workspace": "2", "class": "foot"})
    monkeypatch.setattr(server.events, "EventStream", lambda: stream)
    clients = iter([[], [kitty]])

    def query(cmd):
        return next(clients) if cmd == "clients" else []

    monkeypatch.setattr(server.hyprctl, "query", query)
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *args: None)
    monkeypatch.setattr(server, "_await_new_window", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_active_address", lambda: None)
    monkeypatch.setattr(server.trust, "note_launched", lambda *args: pytest.fail("claimed kitty"))

    result = server.launch("foot", workspace="2", wait_s=1)

    assert isinstance(result, str) and "couldn't safely associate" in result


def test_launch_event_and_polling_share_one_deadline(monkeypatch):
    elapsed = [0.0]
    polling_budgets = []
    polling_deadlines = []

    class SlowStream(FakeStream):
        def wait_for(self, names, matcher, timeout):
            elapsed[0] += timeout
            return None

    monkeypatch.setattr(server.events, "EventStream", lambda: SlowStream(None))
    monkeypatch.setattr(server.hyprctl, "query", lambda cmd: [])
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *args: None)
    monkeypatch.setattr(server.time, "monotonic", lambda: elapsed[0])

    def poll(before, wait_s, accept=None, *, deadline=None):
        polling_budgets.append(wait_s)
        polling_deadlines.append(deadline)
        return None

    monkeypatch.setattr(server, "_await_new_window", poll)
    server._launch_and_wait("foot", 2)

    assert elapsed[0] + sum(polling_budgets) <= 2.001
    assert polling_deadlines == [2.0]


def test_launch_docs_describe_wrapper_class_ambiguity():
    docs = (server.__file__.replace("src/omnimcp/server.py", "docs/CORE.md"))
    with open(docs, encoding="utf-8") as source:
        text = source.read().lower()
    assert "xdg-open" in text and "python app.py" in text
    assert "ambiguous" in text and "class" in text


def test_wait_for_tool_matching(monkeypatch):
    hits = iter([("openwindow", {"address": "0xc", "class": "firefox", "title": "Docs"})])

    class S:
        def wait_for(self, names, matcher, timeout):
            for name, p in hits:
                if matcher is None or matcher(name, p):
                    return name, p
            return None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

    monkeypatch.setattr(server.events, "EventStream", lambda: S())
    out = server.wait_for("window_open", match="FIRE")
    assert out["class"] == "firefox"


def test_wait_for_rejects_unknown_event():
    with pytest.raises(ValueError, match="unknown event"):
        server.wait_for("coffee_ready")


# --- workspace arguments are not free-form ----------------------------------
#
# `hypr action=workspace` is deliberately the one action that skips the
# confinement guard, and on a Lua config `hyprctl dispatch` evaluates its
# argument inside the compositor's own interpreter. A workspace identifier
# never contains this punctuation, so refusing it costs nothing real.


@pytest.mark.parametrize(
    "workspace",
    ['3") or os.execute("touch /tmp/pwn', "3;4", "3,address:0xa", "a=b", "x\ny"],
)
def test_workspace_refuses_expression_punctuation(workspace):
    with pytest.raises(ValueError, match="is not a workspace"):
        server._workspace(workspace)


@pytest.mark.parametrize(
    "workspace", ["3", "-3", "+1", "e+1", "previous", "special:magic", "name:my notes"]
)
def test_workspace_keeps_every_shape_hyprland_accepts(workspace):
    assert server._workspace(workspace) == workspace


def test_hypr_refuses_a_bad_workspace_before_dispatching(monkeypatch):
    monkeypatch.setattr(server.safety, "touch", lambda *a: None)
    dispatched = []
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *a: dispatched.append(a))
    with pytest.raises(ValueError, match="is not a workspace"):
        server.hypr("workspace", workspace='3") or os.execute("id')
    assert dispatched == []


def test_launch_refuses_a_bad_workspace_before_spawning(monkeypatch):
    monkeypatch.setattr(server.safety, "touch", lambda *a: None)
    dispatched = []
    monkeypatch.setattr(server.hyprctl, "dispatch", lambda *a: dispatched.append(a))
    with pytest.raises(ValueError, match="is not a workspace"):
        server.launch("foot", workspace="2] tag pwned [")
    assert dispatched == []


@pytest.mark.parametrize(
    "ws, expect",
    [({"address": "special:scratch", "type": "special", "name": "special:scratch"},
      "special:scratch"),
     ({"address": "notes", "type": "normal", "name": "notes"}, "notes")],
)
def test_launch_reports_an_id_less_057_workspace_by_name(monkeypatch, no_sleep, ws, expect):
    # Hyprland 0.57 gives special and named workspaces no id
    fake = FakeHyprctl([[EXISTING], [EXISTING, dict(CHROME, workspace=ws)]])
    _patch(monkeypatch, fake)
    out = server.launch("google-chrome")
    assert out["workspace"] == expect


@pytest.mark.parametrize("workspace", [
    "3", "+1", "-1", "e+1", "name:research_1.a-b", "previous", "empty",
    "special:notes_1.a-b",
])
def test_launch_workspace_safe_selectors(workspace):
    server._validate_launch_workspace(workspace)


@pytest.mark.parametrize("workspace", [
    " name:foo", "name:foo ", "name:a b", "name:", "special:", "1,2", "1;2",
    "1[2]", "1\n2", "1\x002", "1\t2", "name:a/b", "m1", "~", "bogus",
    "m+1", "m-1", "e-1", "r+1", "r-1", "~2", "special",
])
def test_launch_workspace_rejects_unsafe_selectors(workspace):
    with pytest.raises(ValueError, match="is not a workspace"):
        server._validate_launch_workspace(workspace)
