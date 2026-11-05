"""Delegate explicit tasks to the installed OpenCode CLI through durable jobs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from agentic_os_mcp.core.registry import Fault


def executable() -> str:
    # User systemd services often have a smaller PATH than interactive shells.
    found = shutil.which("opencode")
    local = Path.home() / ".opencode/bin/opencode"
    if not found and local.is_file():
        import os

        if os.access(local, os.X_OK):
            found = str(local)
    if not found:
        raise Fault("missing_dependency", "Install and authenticate OpenCode before delegation.")
    return found


def availability() -> dict:
    try:
        return {"status": "available", "executable": executable()}
    except Fault as exc:
        return exc.result()


def run(
    ctx,
    prompt: str,
    cwd: str,
    model: str = "",
    agent: str = "",
    session_id: str = "",
    auto_approve: bool = False,
    timeout_s: float = 3600,
) -> dict:
    """Run an explicit OpenCode subagent task in cwd. Uses existing OpenCode credentials
    and model settings; model/agent optionally override them. session_id continues a
    previous session. auto_approve opts into --auto (explicit permission denials still
    apply). Runs a private server so job cancellation controls its process group.
    Returns answer, session_id and retained raw output; verify requested changes yourself.
    """
    if not prompt.strip() or len(prompt.encode()) > 64000 or "\0" in prompt:
        raise Fault("invalid_params", "prompt must contain 1..64000 UTF-8 bytes without NUL.")
    directory = Path(cwd).expanduser()
    if not cwd or not directory.is_absolute() or not directory.is_dir():
        raise Fault("invalid_params", "cwd must be an existing absolute project directory.")
    if not 0 < timeout_s <= 86400:
        raise Fault("invalid_params", "timeout_s must be within (0,86400].")
    argv = [executable(), "run", "--standalone", "--format", "json"]
    for flag, value in (("model", model), ("agent", agent), ("session", session_id)):
        if "\0" in value or len(value.encode()) > 1024:
            raise Fault("invalid_params", f"{flag} must be at most 1024 bytes without NUL.")
        if value:
            argv.append(f"--{flag}={value}")
    if auto_approve:
        argv.append("--auto")
    argv.extend(["--", prompt])
    result = ctx.run(argv, cwd=str(directory.resolve()), timeout=timeout_s)
    # Read the full retained stream, not ctx.run's bounded preview. Do not include
    # reasoning/tool arguments in the answer returned to the parent agent.
    answer_ref, answer_path = ctx.store.artifact_path("opencode-answer")
    errors = []
    with (
        ctx.store.path(result["output"]).open(encoding="utf-8", errors="replace") as stream,
        answer_path.open("w", encoding="utf-8") as answer,
    ):
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            sid = event.get("sessionID") or event.get("session_id")
            if isinstance(sid, str) and sid:
                session_id = sid
            part = event.get("part")
            if event.get("type") == "text" and isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    answer.write(text)
            if event.get("type") == "error":
                errors.append(event.get("error", event))
                errors = errors[-5:]
    result.pop("text", None)
    result.update(
        session_id=session_id,
        cwd=str(directory.resolve()),
        answer=ctx.store.read(answer_ref)["data"],
        answer_artifact=answer_ref,
        answer_bytes=answer_path.stat().st_size,
    )
    if errors:
        result["errors"] = errors
        if result["status"] == "ok":
            result["status"] = "failed"
    if result["status"] == "ok" and not result["answer_bytes"]:
        result.update(
            status="invalid_response", message="OpenCode returned no text answer; read output."
        )
    return result


def register(registry):
    registry.add(
        "opencode.run",
        run,
        available=availability,
        resources=lambda args: ("opencode:" + str(Path(args["cwd"]).expanduser().resolve()),),
        verification="OpenCode reply and exit status only; independently verify task effects.",
        example={"prompt": "Explain this project's entry point.", "cwd": "/absolute/project"},
    )
