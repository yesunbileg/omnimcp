"""The per-call auth override is disabled unless the owner opts in."""

import pytest

from omnimcp import server, trust


@pytest.mark.parametrize("handler,args", [
    (server.pointer, {"action": "bad", "allow_auth": True}),
    (server.keyboard, {"action": "bad", "allow_auth": True}),
    (server.click_ui, {"allow_auth": True}),
])
def test_handler_rejects_override_before_other_validation(
    no_real_desktop, monkeypatch, handler, args
):
    monkeypatch.delenv("OMNIMCP_ALLOW_AUTH_OVERRIDE", raising=False)
    with pytest.raises(trust.TrustError, match="OMNIMCP_ALLOW_AUTH_OVERRIDE"):
        handler(**args)


def test_sequence_preflights_override_before_running_any_step(no_real_desktop, monkeypatch):
    monkeypatch.delenv("OMNIMCP_ALLOW_AUTH_OVERRIDE", raising=False)
    ran = []
    monkeypatch.setattr(server, "_dispatch_step", lambda step: ran.append(step))
    with pytest.raises(trust.TrustError, match="OMNIMCP_ALLOW_AUTH_OVERRIDE"):
        server.sequence([
            {"op": "wait_for", "event": "never"},
            {"op": "pointer", "action": "click", "allow_auth": True},
        ], then="none")
    assert ran == []


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_owner_opt_in_allows_override(no_real_desktop, monkeypatch, value):
    monkeypatch.setenv("OMNIMCP_ALLOW_AUTH_OVERRIDE", value)
    assert trust._allow_auth_override_enabled()
    trust.guard_allow_auth_override(True)
