"""Execution contract and filesystem preservation tests (no ambient desktop/system mutations)."""

import base64
import json
import os
import stat
import sys
import time
from typing import Annotated

import pytest
from pydantic import AliasPath, BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from omnimcp.adapters import build_registry
from omnimcp.core.engine import Engine
from omnimcp.core.execution import Context
from omnimcp.core.registry import Fault, Registry
from omnimcp.core.state import BUDGET, Store, encode


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "state")
    yield result
    result.close()


@pytest.fixture
def engine(store):
    value = Engine(build_registry(), store)
    yield value
    value.close()


def settled(engine, ref):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        job = engine.request({"op": "job", "job_id": ref})
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.02)
    pytest.fail("Job did not finish")


def test_observe_rejects_changes_unknown_fields_and_untyped_arguments(engine, tmp_path):
    path = tmp_path / "never-created"
    params = {"path": str(path), "text": "bad", "expected_revision": "missing"}
    assert (
        engine.request({"op": "observe", "action": "file.write", "params": params})["status"]
        == "permission_required"
    )
    assert not path.exists()
    assert (
        engine.request({"op": "act", "action": "system.snapshot", "params": {"extra": 1}})["status"]
        == "invalid_params"
    )
    assert (
        engine.request({"op": "observe", "action": "file.read", "params": {"path": 42}})["status"]
        == "invalid_params"
    )
    assert engine.request({"op": "observe", "action": "unknown"})["status"] == "unsupported"
    schema = engine.request({"op": "discover", "action": "canvas.read"})["parameters"]
    assert "action" not in schema["properties"] and "changes" not in schema["properties"]


def test_projection_filter_and_pagination(store):
    r = Registry()
    r.add(
        "rows",
        lambda ctx: [{"id": n, "kind": n % 2, "big": "ignored"} for n in range(10)],
        readonly=True,
    )
    e = Engine(r, store)
    result = e.request(
        {
            "op": "observe",
            "action": "rows",
            "fields": ["id"],
            "filter": {"kind": 1},
            "offset": 1,
            "limit": 2,
        }
    )
    assert result == {"items": [{"id": 3}, {"id": 5}], "total": 5, "next": 3}
    assert e.request({"op": "discover", "limit": -1})["status"] == "invalid_params"
    e.close()


def test_large_results_recover_exactly_and_byte_offsets(store):
    value = {"unicode": "Монгол\n" * 20000}
    bounded = store.bound(value)
    assert len(encode(bounded).encode()) <= BUDGET
    assert bounded["complete"] is False
    data, offset = bytearray(), 0
    while True:
        chunk = store.read(bounded["artifact"], offset, 37, True)
        data += base64.b64decode(chunk["data"])
        if chunk["next"] is None:
            break
        offset = chunk["next"]
    assert json.loads(data) == value
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path(bounded["artifact"]).stat().st_mode) == 0o600


def test_revision_backup_restore_preview_and_conflict(engine, tmp_path):
    p = tmp_path / "config"
    p.write_text("before\n")
    p.chmod(0o640)
    first = engine.request({"op": "observe", "action": "file.read", "params": {"path": str(p)}})
    params = {
        "path": str(p),
        "before": "before",
        "after": "after",
        "expected_revision": first["revision"],
    }
    preview = engine.request(
        {
            "op": "act",
            "action": "file.patch",
            "params": {**params, "preview": True},
            "background": False,
        }
    )
    assert preview["preview"] and "-before" in preview["diff"] and p.read_text() == "before\n"
    changed = engine.request(
        {"op": "act", "action": "file.patch", "params": params, "background": False}
    )
    assert changed["verified"] and p.read_text() == "after\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o640
    assert (
        engine.request(
            {"op": "act", "action": "file.patch", "params": params, "background": False}
        )["status"]
        == "stale_revision"
    )
    restored = engine.request({"op": "act", **changed["undo"], "background": False})
    assert restored["verified"] and p.read_text() == "before\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o640


def test_resource_lock_prevents_two_successful_writes_of_same_revision(engine, tmp_path):
    p = tmp_path / "raced"
    p.write_text("initial")
    first = engine.request({"op": "observe", "action": "file.read", "params": {"path": str(p)}})
    jobs = [
        engine.request(
            {
                "op": "act",
                "action": "file.write",
                "params": {"path": str(p), "text": str(n), "expected_revision": first["revision"]},
            }
        )["job_id"]
        for n in range(2)
    ]
    results = [settled(engine, j)["result"]["status"] for j in jobs]
    assert sorted(results) == ["ok", "stale_revision"]


def test_worker_restart_marks_jobs_interrupted_without_replay(store):
    ref = store.create_job("file.write")
    store.update_job(ref, "running")
    store.recover()
    assert store.job(ref)["status"] == "interrupted"
    assert store.job(ref)["result"]["status"] == "interrupted"


def test_cancel_command_and_full_output(engine):
    ref = engine.request(
        {
            "op": "act",
            "action": "command.exec",
            "params": {
                "argv": [sys.executable, "-u", "-c", 'import time; print("ready"); time.sleep(30)']
            },
        }
    )["job_id"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        progress = engine.store.job(ref)["progress"]
        if progress and engine.store.read(progress["output"])["data"] == "ready\n":
            break
        time.sleep(0.02)
    engine.request({"op": "job", "job_id": ref, "cancel": True})
    result = settled(engine, ref)
    assert result["status"] == "cancelled"
    assert result["result"]["text"] == "ready\n"
    assert result["result"]["exit_code"] != 0


def test_missing_dependency_is_not_execution_failure(store):
    r = Registry()
    r.add(
        "missing",
        lambda ctx: pytest.fail("must not execute"),
        dependencies=("aos-nonexistent-backend-314159",),
    )
    e = Engine(r, store)
    assert (
        e.request({"op": "discover", "action": "missing"})["availability"]["status"]
        == "missing_dependency"
    )
    assert (
        e.request({"op": "act", "action": "missing", "background": False})["status"]
        == "missing_dependency"
    )
    e.close()


def test_readonly_and_dryrun_are_enforced_by_worker(engine, tmp_path):
    path = tmp_path / "unchanged"
    request = {
        "op": "act",
        "action": "file.write",
        "params": {"path": str(path), "text": "x", "expected_revision": "missing"},
        "background": False,
    }
    engine.readonly = True
    assert engine.request(request)["status"] == "permission_required"
    engine.readonly = False
    engine.dryrun = True
    assert engine.request(request)["status"] == "dry_run"
    assert not path.exists()
    assert (
        engine.request({"op": "discover", "readonly": True, "action": "file.write"})["status"]
        == "permission_required"
    )


def test_workflow_refs_conditions_assertions_and_waits(store):
    r, calls = Registry(), []

    def read(ctx):
        calls.append(1)
        return {"status": "ok", "value": len(calls)}

    def write(ctx, value: int):
        return {"status": "ok", "echo": value}

    r.add("read", read, readonly=True, idempotent=True)
    r.add("write", write)
    e = Engine(r, store)
    steps = [
        {
            "id": "read",
            "action": "read",
            "wait": {"path": "value", "equals": 2, "timeout_s": 1, "interval_s": 0.05},
        },
        {
            "id": "write",
            "action": "write",
            "params": {"value": {"$ref": "read.value"}},
            "assert": {"path": "echo", "equals": 2},
        },
        {"id": "skip", "action": "read", "when": {"path": "write.echo", "equals": 0}},
    ]
    result = settled(e, e.request({"op": "workflow", "steps": steps})["job_id"])
    assert result["status"] == "succeeded"
    assert result["result"]["steps"]["skip"]["status"] == "skipped"
    assert result["result"]["steps"]["write"]["echo"] == 2
    invalid = e.request(
        {
            "op": "workflow",
            "steps": [{"id": "bad", "action": "write", "params": {"value": 1}, "retry": 1}],
        }
    )
    assert invalid["status"] == "invalid_params"
    e.close()


def test_workflow_deadline_stops_subprocess_and_does_not_continue(engine, tmp_path):
    marker = tmp_path / "must-not-exist"
    result = engine.request(
        {
            "op": "workflow",
            "timeout_s": 0.15,
            "steps": [
                {
                    "id": "wait",
                    "action": "command.exec",
                    "params": {"argv": [sys.executable, "-c", "import time; time.sleep(30)"]},
                },
                {
                    "id": "write",
                    "action": "file.write",
                    "params": {"path": str(marker), "text": "bad", "expected_revision": "missing"},
                },
            ],
        }
    )
    assert settled(engine, result["job_id"])["result"]["status"] == "timeout"
    assert not marker.exists()


def test_auth_cancellation_is_persisted_and_never_auto_reprompts(store, tmp_path, monkeypatch):
    fake = tmp_path / "pkexec"
    calls = tmp_path / "calls"
    fake.write_text(f'#!/bin/sh\nprintf x >> "{calls}"\nexit 126\n')
    fake.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("WAYLAND_DISPLAY", "test-display")
    ctx = Context(store)
    assert ctx.run(["/usr/bin/true"], admin=True)["status"] == "auth_cancelled"
    with pytest.raises(Fault, match="Previous authentication"):
        ctx.run(["/usr/bin/false"], admin=True)
    assert calls.read_text() == "x"
    retry = Context(store, auth_retry=True)
    with pytest.raises(Fault, match="Previous authentication"):
        retry.run(["/usr/bin/true"], admin=True)
    assert calls.read_text() == "x"


def test_stale_process_ref_is_rejected(engine):
    assert (
        engine.request(
            {
                "op": "act",
                "action": "process.signal",
                "params": {"ref": "expired"},
                "background": False,
            }
        )["status"]
        == "stale_reference"
    )


def test_compact_schema_has_seven_tools_and_no_duplicate_results(monkeypatch):
    import asyncio

    from omnimcp import compact

    monkeypatch.delenv("OMNIMCP_READONLY", raising=False)

    async def go():
        app = compact.build_app()
        tools = await app.list_tools()
        assert {t.name for t in tools} == {
            "discover",
            "observe",
            "act",
            "workflow",
            "job",
            "events",
            "artifact",
        }
        assert all(t.outputSchema is None for t in tools)

    asyncio.run(go())


def test_window_refs_reject_reused_addresses_and_previous_sessions(monkeypatch):
    from omnimcp import hyprctl
    from omnimcp.adapters.desktop import WindowRefs

    refmap = WindowRefs()
    client = {"address": "0x123", "stableId": 1, "pid": 234}
    monkeypatch.setattr(hyprctl, "query", lambda _: [client])
    snapshot = refmap.snapshot({"windows": [client], "active_window": "0x123"})
    ref = snapshot["active_window"]
    assert ref != "0x123" and snapshot["windows"][0]["address"] == ref
    assert refmap.resolve(ref) == "0x123"
    client["stableId"] = 2
    with pytest.raises(Fault, match="identity changed"):
        refmap.resolve(ref)
    with pytest.raises(Fault, match="expired"):
        WindowRefs().args({"window": ref})


def test_admin_success_timeout_requires_local_reset_before_retry(store, tmp_path, monkeypatch):
    fake = tmp_path / "pkexec"
    fake.write_text('#!/bin/sh\nexec "$@"\n')
    fake.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("WAYLAND_DISPLAY", "test-display")
    assert Context(store).run(["/usr/bin/true"], admin=True)["status"] == "ok"
    assert (
        Context(store).run(["/usr/bin/sleep", "30"], admin=True, timeout=0.05)["status"]
        == "auth_timeout"
    )
    retry = Context(store, auth_retry=True)
    fake.write_text("#!/bin/sh\nexit 126\n")
    with pytest.raises(Fault, match="Previous authentication"):
        retry.run(["/usr/bin/true"], admin=True)
    store.auth_block("gui-auth", clear=True)
    assert retry.run(["/usr/bin/true"], admin=True)["status"] == "auth_cancelled"
    with pytest.raises(Fault, match="Previous authentication"):
        retry.run(["/usr/bin/true"], admin=True)


def test_socket_boolean_fields_are_strict(engine):
    assert (
        engine.request({"op": "act", "action": "system.snapshot", "auth_retry": "false"})["status"]
        == "invalid_params"
    )
    assert engine.request({"op": "job", "cancel": True})["status"] == "invalid_params"


def test_workflow_cannot_queue_invalid_static_params_after_a_valid_change(engine, tmp_path):
    marker = tmp_path / "must-not-change"
    result = engine.request(
        {
            "op": "workflow",
            "steps": [
                {
                    "id": "write",
                    "action": "file.write",
                    "params": {"path": str(marker), "text": "bad", "expected_revision": "missing"},
                },
                {
                    "id": "bad",
                    "action": "service.restart",
                    "params": {"unit": "fixture", "unknown": True},
                },
            ],
        }
    )
    assert result["status"] == "invalid_params"
    assert not marker.exists()


@pytest.mark.parametrize(
    "bad_params",
    [
        {
            "value": {"$ref": "source.value"},
            "label": "label",
            "settings": {"count": 1},
            "unknown": True,
        },
        {"value": {"$ref": "source.value"}},
        {
            "value": {"$ref": "source.value"},
            "label": 7,
            "settings": {"count": 1},
        },
        {
            "value": {"$ref": "source.value"},
            "label": "label",
            "settings": {"count": "wrong"},
        },
    ],
    ids=["unknown-field", "missing-field", "wrong-static-type", "nested-static-type"],
)
def test_workflow_preflights_static_params_even_when_other_fields_are_refs(
    store, tmp_path, bad_params
):
    marker = tmp_path / "must-not-be-written"
    r = Registry()

    def source(ctx):
        return {"status": "ok", "value": 3}

    def mark(ctx, path: str):
        marker.write_text("changed")
        return {"status": "ok"}

    def consume(ctx, value: int, label: str, settings: dict[str, int]):
        return {"status": "ok"}

    r.add("source", source, readonly=True)
    r.add("mark", mark)
    r.add("consume", consume)
    e = Engine(r, store)
    try:
        result = e.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "mark", "action": "mark", "params": {"path": str(marker)}},
                    {"id": "source", "action": "source"},
                    {"id": "bad", "action": "consume", "params": bad_params},
                ],
            }
        )
        assert result["status"] == "invalid_params"
        assert not marker.exists()
        assert store.job()["items"] == []
    finally:
        e.close()


@pytest.mark.parametrize(
    "condition",
    [
        {"path": "future.value", "equals": 1},
        {"path": "current.value", "equals": 1},
        {"path": "unknown.value", "equals": 1},
        {"path": "prior.value", "equals": {"$ref": "future.value"}},
        {"path": "prior.value", "equals": {"$ref": "unknown.value"}},
    ],
    ids=[
        "future-when-root",
        "self-when-root",
        "unknown-when-root",
        "future-equals-ref",
        "unknown-equals-ref",
    ],
)
def test_workflow_rejects_invalid_when_references_before_queue(store, condition):
    r = Registry()
    r.add("read", lambda ctx: {"status": "ok", "value": 1}, readonly=True)
    e = Engine(r, store)
    try:
        result = e.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "prior", "action": "read"},
                    {"id": "current", "action": "read", "when": condition},
                    {"id": "future", "action": "read"},
                ],
            }
        )
        assert result["status"] == "invalid_reference"
        assert store.job()["items"] == []
    finally:
        e.close()


@pytest.mark.parametrize(
    "key,condition",
    [
        ("wait", {"path": "value", "equals": {"$ref": "current.value"}}),
        ("assert", {"path": "value", "equals": {"$ref": "future.value"}}),
    ],
    ids=["wait-equals-current-ref", "assert-equals-future-ref"],
)
def test_workflow_rejects_non_prior_condition_equals_refs_before_queue(store, key, condition):
    r = Registry()
    r.add("read", lambda ctx: {"status": "ok", "value": 1}, readonly=True)
    e = Engine(r, store)
    try:
        result = e.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "prior", "action": "read"},
                    {"id": "current", "action": "read", key: condition},
                    {"id": "future", "action": "read"},
                ],
            }
        )
        assert result["status"] == "invalid_reference"
        assert store.job()["items"] == []
    finally:
        e.close()


def test_workflow_keeps_nested_refs_defaults_and_local_assert_wait_paths(store):
    r = Registry()

    def read(ctx):
        return {"status": "ok", "value": 7}

    def echo(ctx, payload: dict[str, dict[str, int]], label: str = "default"):
        return {"status": "ok", "payload": payload, "label": label}

    r.add("read", read, readonly=True)
    r.add("echo", echo)
    e = Engine(r, store)
    try:
        result = e.request(
            {
                "op": "workflow",
                "steps": [
                    {
                        "id": "read",
                        "action": "read",
                        "wait": {"path": "value", "equals": 7},
                    },
                    {
                        "id": "echo",
                        "action": "echo",
                        "params": {"payload": {"nested": {"value": {"$ref": "read.value"}}}},
                        "assert": {
                            "path": "payload.nested.value",
                            "equals": {"$ref": "echo.payload.nested.value"},
                        },
                    },
                ],
            }
        )
        settled_result = settled(e, result["job_id"])
        assert settled_result["status"] == "succeeded"
        assert settled_result["result"]["steps"]["echo"] == {
            "status": "ok",
            "payload": {"nested": {"value": 7}},
            "label": "default",
        }
    finally:
        e.close()


def test_workflow_allows_whole_params_reference_and_runtime_defaults(store):
    r = Registry()

    def source(ctx):
        return {"status": "ok", "args": {"value": 4}}

    def consume(ctx, value: int, label: str = "default"):
        return {"status": "ok", "value": value, "label": label}

    r.add("source", source, readonly=True)
    r.add("consume", consume)
    e = Engine(r, store)
    try:
        request = e.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "source", "action": "source"},
                    {"id": "consume", "action": "consume", "params": {"$ref": "source.args"}},
                ],
            }
        )
        result = settled(e, request["job_id"])
        assert result["status"] == "succeeded"
        assert result["result"]["steps"]["consume"] == {
            "status": "ok",
            "value": 4,
            "label": "default",
        }
    finally:
        e.close()


@pytest.mark.parametrize(
    "container_type,one_ref",
    [
        (list[int], [{"$ref": "source.value"}]),
        (dict[str, int], {"one": {"$ref": "source.value"}}),
        (list[int] | None, [{"$ref": "source.value"}]),
        (dict[str, int] | None, {"one": {"$ref": "source.value"}}),
    ],
    ids=[
        "constrained-list", "constrained-dict",
        "constrained-optional-list", "constrained-optional-dict",
    ],
)
def test_workflow_preflights_constrained_container_with_dynamic_items(
    store, tmp_path, container_type, one_ref
):
    marker = tmp_path / "must-not-run-before-container-check"
    r = Registry()

    def source(ctx):
        return {"status": "ok", "value": 1}

    def mark(ctx, path: str):
        marker.write_text("changed")
        return {"status": "ok"}

    def consume(ctx, values: list[int]):
        return {"status": "ok"}

    r.add("source", source, readonly=True)
    r.add("mark", mark)
    r.add(
        "consume",
        consume,
        params={"values": (Annotated[container_type, Field(min_length=2)], ...)},
    )
    e = Engine(r, store)
    try:
        result = e.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "mark", "action": "mark", "params": {"path": str(marker)}},
                    {"id": "source", "action": "source"},
                    {"id": "bad", "action": "consume", "params": {"values": one_ref}},
                ],
            }
        )
        assert result["status"] == "invalid_params"
        assert not marker.exists()
        assert store.job()["items"] == []
    finally:
        e.close()


def test_workflow_accepts_nested_model_input_using_action_model_contract(store):
    class Payload(BaseModel):
        value: int

    r = Registry()

    def source(ctx):
        return {"status": "ok", "args": {"payload": {"value": 4}}}

    def consume(ctx, payload: Payload):
        return {"status": "ok", "value": payload["value"]}

    r.add("source", source, readonly=True)
    r.add("consume", consume)
    e = Engine(r, store)
    try:
        request = e.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "source", "action": "source"},
                    {"id": "consume", "action": "consume", "params": {"payload": {"value": 4}}},
                ],
            }
        )
        result = settled(e, request["job_id"])
        assert result["status"] == "succeeded"
        assert result["result"]["steps"]["consume"]["value"] == 4
    finally:
        e.close()


@pytest.mark.parametrize("use_reference", [False, True], ids=["static", "nested-reference"])
def test_workflow_accepts_nested_typed_dict_input(store, use_reference):
    class Payload(TypedDict):
        value: int

    r = Registry()

    def source(ctx):
        return {"status": "ok", "value": 4}

    def consume(ctx, payload: Payload):
        return {"status": "ok", "value": payload["value"]}

    r.add("source", source, readonly=True)
    r.add("consume", consume)
    e = Engine(r, store)
    try:
        payload = {"value": {"$ref": "source.value"}} if use_reference else {"value": 4}
        steps = []
        if use_reference:
            steps.append({"id": "source", "action": "source"})
        steps.append({"id": "consume", "action": "consume", "params": {"payload": payload}})
        request = e.request({"op": "workflow", "steps": steps})
        result = settled(e, request["job_id"])
        assert result["status"] == "succeeded"
        assert result["result"]["steps"]["consume"]["value"] == 4
    finally:
        e.close()


def test_workflow_accepts_nested_model_alias_and_allowed_extra_with_refs(store):
    class Payload(BaseModel):
        model_config = ConfigDict(extra="allow")

        value: int = Field(alias="wire_value")

    r = Registry()

    def source(ctx):
        return {"status": "ok", "value": 4}

    def consume(ctx, payload: Payload):
        return {"status": "ok", "value": payload["value"], "note": payload["note"]}

    r.add("source", source, readonly=True)
    r.add("consume", consume)
    e = Engine(r, store)
    try:
        request = e.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "source", "action": "source"},
                    {
                        "id": "consume",
                        "action": "consume",
                        "params": {
                            "payload": {
                                "wire_value": {"$ref": "source.value"},
                                "note": "kept",
                            }
                        },
                    },
                ],
            }
        )
        result = settled(e, request["job_id"])
        assert result["status"] == "succeeded"
        assert result["result"]["steps"]["consume"] == {
            "status": "ok",
            "value": 4,
            "note": "kept",
        }
    finally:
        e.close()


def test_workflow_resolves_nested_model_alias_path_with_ref(store):
    class Payload(BaseModel):
        model_config = ConfigDict(extra="allow")

        value: int = Field(validation_alias=AliasPath("wire", "value"))

    r = Registry()

    def source(ctx):
        return {"status": "ok", "value": 4}

    def consume(ctx, payload: Payload):
        return {"status": "ok", "value": payload["value"], "note": payload["note"]}

    r.add("source", source, readonly=True)
    r.add("consume", consume)
    e = Engine(r, store)
    try:
        request = e.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "source", "action": "source"},
                    {
                        "id": "consume",
                        "action": "consume",
                        "params": {
                            "payload": {
                                "wire": {"value": {"$ref": "source.value"}},
                                "note": "kept",
                            }
                        },
                    },
                ],
            }
        )
        result = settled(e, request["job_id"])
        assert result["status"] == "succeeded"
        assert result["result"]["steps"]["consume"] == {
            "status": "ok",
            "value": 4,
            "note": "kept",
        }
    finally:
        e.close()


def test_workflow_accepts_top_level_action_field_alias_with_ref(store):
    r = Registry()

    def source(ctx):
        return {"status": "ok", "value": 4}

    def consume(ctx, value: int):
        return {"status": "ok", "value": value}

    r.add("source", source, readonly=True)
    r.add("consume", consume, params={"value": (int, Field(alias="wire_value"))})
    e = Engine(r, store)
    try:
        request = e.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "source", "action": "source"},
                    {
                        "id": "consume",
                        "action": "consume",
                        "params": {"wire_value": {"$ref": "source.value"}},
                    },
                ],
            }
        )
        result = settled(e, request["job_id"])
        assert result["status"] == "succeeded"
        assert result["result"]["steps"]["consume"]["value"] == 4
    finally:
        e.close()


@pytest.mark.parametrize(
    "alias,static_params",
    [(AliasPath("wire"), {}), (AliasPath("wire", 0), {"wire": "x"})],
    ids=["missing-nullable-root", "cannot-traverse-string"],
)
def test_workflow_alias_paths_reject_missing_values_before_mutation(
    store, tmp_path, alias, static_params
):
    marker = tmp_path / "must-not-be-created"
    registry = Registry()

    def source(ctx):
        marker.write_text("mutated")
        return {"status": "ok", "value": 1}

    registry.add("source", source)
    registry.add(
        "consume",
        lambda ctx, maybe, value: {"status": "ok"},
        params={"maybe": (str | None, Field(validation_alias=alias)), "value": (int, ...)},
    )
    engine = Engine(registry, store)
    try:
        result = engine.request(
            {
                "op": "workflow",
                "steps": [
                    {"id": "source", "action": "source"},
                    {
                        "id": "consume",
                        "action": "consume",
                        "params": {**static_params, "value": {"$ref": "source.value"}},
                    },
                ],
            }
        )
        assert result["status"] == "invalid_params"
        assert not marker.exists()
        assert store.job()["items"] == []
    finally:
        engine.close()


def test_unchanged_kernel_managed_xattrs_are_preserved_without_setting(
    engine, tmp_path, monkeypatch
):
    path = tmp_path / "metadata"
    path.write_text("old")
    first = engine.request({"op": "observe", "action": "file.read", "params": {"path": str(path)}})
    monkeypatch.setattr(os, "listxattr", lambda p: ["$LXUID", "$LXGID", "$LXMOD"])
    monkeypatch.setattr(os, "getxattr", lambda p, key: b"unchanged-kernel-metadata")
    monkeypatch.setattr(
        os, "setxattr", lambda *a: pytest.fail("Kernel-managed metadata already matches")
    )
    result = engine.request(
        {
            "op": "act",
            "action": "file.write",
            "background": False,
            "params": {"path": str(path), "text": "new", "expected_revision": first["revision"]},
        }
    )
    assert result["verified"] and path.read_text() == "new"


def test_elevated_signal_denial_does_not_claim_cancellation(store, tmp_path, monkeypatch):
    import signal

    import psutil

    fake = tmp_path / "pkexec"
    fake.write_text('#!/bin/sh\nexec "$@"\n')
    fake.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("WAYLAND_DISPLAY", "test-display")

    def denied(*args):
        raise PermissionError("simulated elevated process")

    monkeypatch.setattr(os, "killpg", denied)
    result = Context(store).run(["/usr/bin/sleep", "30"], admin=True, timeout=0.05)
    try:
        assert result["status"] == "timeout_pending" and result["still_running"]
        assert store.auth_block("gui-auth")
    finally:
        proc = psutil.Process(result["pid"])
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=2)
