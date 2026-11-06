"""OpenCode boundary: real child processes, retained output, jobs and MCP schema."""

import asyncio
import json
import os
import time

import pytest

from omnimcp.adapters import build_registry
from omnimcp.core.engine import Engine
from omnimcp.core.state import Store
from omnimcp.opencode import opencode


@pytest.fixture
def engine(tmp_path, monkeypatch):
    child = tmp_path / "opencode"
    child.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time\n"
        "prompt = sys.argv[-1]\n"
        'if prompt == "sleep":\n'
        '    print("started", flush=True); time.sleep(30)\n'
        'elif prompt == "error":\n'
        '    print(json.dumps({"type":"error", "error":{"message":"bad model"}}))\n'
        'elif prompt == "empty":\n'
        "    pass\n"
        "else:\n"
        '    print("diagnostic " + "x" * 10000)\n'
        '    print(json.dumps({"type":"text", "sessionID":"ses_fixture",\n'
        '        "part":{"text":json.dumps({"argv":sys.argv[1:],\n'
        '        "cwd":__import__("os").getcwd()})}}))\n'
    )
    child.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + ":" + os.environ["PATH"])
    monkeypatch.delenv("OMNIMCP_DRYRUN", raising=False)
    monkeypatch.delenv("OMNIMCP_READONLY", raising=False)
    store = Store(tmp_path / "state")
    value = Engine(build_registry(), store)
    yield value
    value.close()
    store.close()


def run(engine, tmp_path, **params):
    return engine.request(
        {
            "op": "act",
            "action": "opencode.run",
            "background": False,
            "params": {"prompt": "literal $(touch nope)", "cwd": str(tmp_path), **params},
        }
    )


def wait(engine, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = engine.request({"op": "job", "job_id": job_id})
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(0.02)
    pytest.fail("job did not stop")


def test_real_child_literal_prompt_flags_and_full_stream(engine, tmp_path):
    result = run(
        engine,
        tmp_path,
        model="local/example",
        agent="plan",
        session_id="ses_previous",
        auto_approve=True,
    )
    assert result["status"] == "ok", result
    assert result["session_id"] == "ses_fixture"
    answer = json.loads(result["answer"])
    assert answer["cwd"] == str(tmp_path)
    assert answer["argv"] == [
        "run",
        "--standalone",
        "--format",
        "json",
        "--model=local/example",
        "--agent=plan",
        "--session=ses_previous",
        "--auto",
        "--",
        "literal $(touch nope)",
    ]
    assert not (tmp_path / "nope").exists()
    assert engine.store.read(result["answer_artifact"])["data"] == result["answer"]
    assert result["bytes"] > 10000  # answer after ctx.run's 8192-byte preview


@pytest.mark.parametrize(
    "params",
    [
        {"prompt": ""},
        {"cwd": "relative"},
        {"timeout_s": 0},
        {"timeout_s": float("inf")},
        {"prompt": "\0"},
    ],
)
def test_invalid_arguments(engine, tmp_path, params):
    assert run(engine, tmp_path, **params)["status"] == "invalid_params"


@pytest.mark.parametrize(
    "prompt,status", [("error", "failed"), ("empty", "invalid_response"), ("sleep", "timeout")]
)
def test_backend_failure_is_not_success(engine, tmp_path, prompt, status):
    result = run(engine, tmp_path, prompt=prompt, timeout_s=0.1 if prompt == "sleep" else 5)
    assert result["status"] == status


def test_cancel_job_and_read_raw_output(engine, tmp_path):
    queued = engine.request(
        {"op": "act", "action": "opencode.run", "params": {"prompt": "sleep", "cwd": str(tmp_path)}}
    )
    job_id = queued["job_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = engine.request({"op": "job", "job_id": job_id})
        if (job.get("progress") or {}).get("output"):
            break
        time.sleep(0.02)
    engine.request({"op": "job", "job_id": job_id, "cancel": True})
    result = wait(engine, job_id)
    assert result["status"] == "cancelled", result
    assert result["result"]["exit_code"] is not None


def test_facade_refuses_unrelated_job_and_readonly(engine, monkeypatch):
    import omnimcp.opencode as facade

    monkeypatch.setattr(facade, "rpc", engine.request)
    unrelated = engine.store.create_job("command.exec")
    assert json.loads(opencode(action="cancel", job_id=unrelated))["status"] == "invalid_params"
    monkeypatch.setenv("OMNIMCP_READONLY", "1")
    assert json.loads(opencode(prompt="hello", cwd="/tmp"))["status"] == "permission_required"
    assert engine.request(
        {"op": "observe", "action": "opencode.run", "params": {"prompt": "hello", "cwd": "/tmp"}}
    )["status"] == ("permission_required")


def test_mcp_tool_registered_without_structured_duplicate(monkeypatch):
    from omnimcp import server

    monkeypatch.setattr(server, "READONLY", False)
    tools = asyncio.run(server.build_app().list_tools())
    tool = next(t for t in tools if t.name == "opencode")
    assert tool.outputSchema is None
    assert tool.inputSchema["properties"]["action"]["enum"] == ["run", "status", "output", "cancel"]
    monkeypatch.setattr(server, "READONLY", True)
    assert "opencode" not in {t.name for t in asyncio.run(server.build_app().list_tools())}


def test_dryrun_never_calls_worker(monkeypatch):
    import omnimcp.opencode as facade

    monkeypatch.setenv("OMNIMCP_DRYRUN", "1")
    monkeypatch.delenv("OMNIMCP_READONLY", raising=False)

    def unexpected(request):
        pytest.fail("dry run contacted worker")

    monkeypatch.setattr(facade, "rpc", unexpected)
    for action in ("run", "cancel"):
        assert json.loads(opencode(action=action))["status"] == "dry_run"
