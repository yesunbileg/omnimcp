"""Verify semantic effects rather than trusting successful command exits."""

from types import SimpleNamespace

from agentic_os_mcp.adapters import native, system


def test_service_restart_checks_actual_state():
    outputs = iter(
        [
            {"status": "ok", "text": "LoadState=loaded\nActiveState=active\nMainPID=100\n"},
            {"status": "ok", "text": ""},
            {"status": "ok", "text": "LoadState=loaded\nActiveState=failed\nMainPID=0\n"},
        ]
    )
    ctx = SimpleNamespace(run=lambda *a, **kw: next(outputs))
    result = system.change(ctx, "fixture.service", "restart", "user")
    assert result["status"] == "verification_failed" and not result["verified"]
    assert result["undo"]["params"]["operation"] == "start"


def test_audio_cannot_claim_success_if_readback_disagrees():
    outputs = iter(
        [
            {"status": "ok", "text": "Volume: 0.50"},
            {"status": "ok", "text": ""},
            {"status": "ok", "text": "Volume: 0.90"},
        ]
    )
    ctx = SimpleNamespace(run=lambda *a, **kw: next(outputs))
    result = native.audio(ctx, "volume", value="25%")
    assert result["status"] == "verification_failed" and not result["verified"]


def test_network_failed_activation_keeps_checkpoint_and_does_not_commit():
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "CheckpointCreate" in argv:
            return {"status": "ok", "text": 'o "/org/freedesktop/NetworkManager/Checkpoint/1"'}
        if "up" in argv:
            return {"status": "auth_cancelled", "text": ""}
        return {"status": "ok", "text": ""}

    ctx = SimpleNamespace(run=run, deadline=float("inf"))
    result = native.network_connect(ctx, "12345678-1234-1234-1234-123456789012")
    assert result["status"] == "auth_cancelled"
    assert result["rollback"] == "NetworkManager timed checkpoint"
    assert not any("CheckpointDestroy" in call for call in calls)
    assert ctx.deadline == float("inf")


def test_container_start_verifies_running_state():
    outputs = iter([{"status": "ok", "text": "fixture"}, {"status": "ok", "text": "false\n"}])
    ctx = SimpleNamespace(run=lambda *a, **kw: next(outputs))
    assert native.container(ctx, "start", "fixture")["status"] == "verification_failed"


def test_browser_maps_ref_using_negotiated_backend_schema():
    from agentic_os_mcp.adapters.browser import adapt_arguments

    params = {"ref": "e3", "element": "Name", "text": "Codex"}
    old = adapt_arguments({"properties": {"ref": {}, "text": {}}}, params)
    new = adapt_arguments({"properties": {"target": {}, "text": {}}}, params)
    assert old["ref"] == "e3" and "target" not in old
    assert new["target"] == "e3" and "ref" not in new
    assert params["ref"] == "e3"
