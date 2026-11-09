"""CLI front door for the worker and compact RPC, beside all legacy verbs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from omnimcp.core.client import rpc
from omnimcp.core.execution import flag
from omnimcp.core.state import encode

OPS = {"discover", "observe", "act", "workflow", "job", "events", "artifact"}


def worker(argv):
    parser = argparse.ArgumentParser(prog="OmniMCP worker")
    operations = parser.add_subparsers(dest="operation", required=True)
    for name in ("run", "install", "status", "start", "stop", "stop-all", "auth-reset"):
        operations.add_parser(name)
    prune = operations.add_parser("prune", help="preview offline artifact cleanup")
    prune.add_argument("--older-than-days", type=float, default=30)
    prune.add_argument("--max-bytes", type=int, default=1024**3)
    prune.add_argument("--apply", action="store_true", help="delete selected artifact bytes")
    args = parser.parse_args(argv)
    if args.operation == "prune":
        from omnimcp.core.registry import Fault
        from omnimcp.core.retention import prune_artifacts

        try:
            if args.apply and (flag("OMNIMCP_READONLY") or flag("OMNIMCP_DRYRUN")):
                raise Fault(
                    "permission_required", "Read-only/dry-run policy blocks artifact deletion."
                )
            result = prune_artifacts(
                older_than_days=args.older_than_days, max_bytes=args.max_bytes, apply=args.apply
            )
        except Fault as exc:
            result = exc.result()
        print(encode(result))
        return 0 if result["status"] == "ok" else 1
    if args.operation == "auth-reset":
        from omnimcp.core.state import Store

        store = Store()
        try:
            store.auth_block("gui-auth", clear=True)
        finally:
            store.close()
        print("GUI authentication block cleared locally; the next admin action may prompt.")
        return 0
    if args.operation == "stop-all":
        result = rpc({"op": "worker_stop_all"}, timeout=10)
        print(encode(result))
        return 0 if result.get("status") == "ok" else 1
    if args.operation == "run":
        from omnimcp.core.worker import main

        old, sys.argv = sys.argv, [sys.argv[0]]
        try:
            main()
        finally:
            sys.argv = old
        return 0
    if args.operation == "install":
        unit = (
            Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            / "systemd/user/omnimcp.service"
        )
        unit.parent.mkdir(parents=True, exist_ok=True)
        # Use the owning interpreter, not PATH's possibly different installed distribution.
        executable = str(Path(sys.executable).absolute()).replace("%", "%%").replace('"', '\\"')
        persisted = ""
        for key in (
            "OMNIMCP_BACKGROUND",
            "OMNIMCP_READONLY",
            "OMNIMCP_DRYRUN",
            "OMNIMCP_CONFINE",
            "OMNIMCP_AGENT_WORKSPACES",
        ):
            if key in os.environ:
                value = (key + "=" + os.environ[key]).replace("%", "%%")
                persisted += "Environment=" + json.dumps(value, ensure_ascii=False) + "\n"
        unit.write_text(
            "[Unit]\nDescription=OmniMCP user worker\nAfter=graphical-session.target\n\n"
            '[Service]\nType=simple\nExecStart="'
            + executable
            + '" -m omnimcp.core.worker\n'
            + persisted
            + "Restart=on-failure\nRestartSec=2\nUMask=0077\nKillMode=control-group\n"
            "TimeoutStopSec=15\n\n[Install]\nWantedBy=default.target\n"
        )
        from omnimcp.core.retention import record_policy

        record_policy(readonly=flag("OMNIMCP_READONLY"), dry_run=flag("OMNIMCP_DRYRUN"))
        result = subprocess.run(["systemctl", "--user", "daemon-reload"])
        if result.returncode:
            return result.returncode
        result = subprocess.run(["systemctl", "--user", "enable", "--now", unit.name])
        print(f"Worker unit: {unit}")
        return result.returncode
    return subprocess.run(
        ["systemctl", "--user", args.operation, "omnimcp.service", "--no-pager"]
    ).returncode


def main(argv):
    if argv[0] == "worker":
        return worker(argv[1:])
    op = argv[0]
    parser = argparse.ArgumentParser(prog="OmniMCP " + op)
    parser.add_argument("target", nargs="?", default="")
    parser.add_argument("--params", type=json.loads, default={})
    parser.add_argument("--query", default="")
    parser.add_argument("--action", default="")
    parser.add_argument("--fields", type=json.loads, default=[])
    parser.add_argument("--filter", type=json.loads, default={})
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--since", type=int, default=0)
    parser.add_argument("--kind", default="")
    parser.add_argument("--length", type=int, default=8192)
    parser.add_argument("--binary", action="store_true")
    parser.add_argument("--cancel", action="store_true")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--auth-retry", action="store_true")
    parser.add_argument("--steps", type=json.loads)
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args(argv[1:])
    req = {"op": op, "readonly": flag("OMNIMCP_READONLY")}
    if op == "discover":
        req.update(
            query=args.query or args.target,
            action=args.action,
            offset=args.offset,
            limit=args.limit,
        )
    elif op in {"observe", "act"}:
        req.update(action=args.action or args.target, params=args.params)
        if op == "observe":
            req.update(fields=args.fields, filter=args.filter, offset=args.offset, limit=args.limit)
        else:
            req.update(background=not args.sync, auth_retry=args.auth_retry)
    elif op == "workflow":
        req.update(steps=args.steps, timeout_s=args.timeout)
    elif op == "job":
        req.update(job_id=args.target, cancel=args.cancel, offset=args.offset, limit=args.limit)
    elif op == "events":
        req.update(since=args.since, kind=args.kind, limit=args.limit)
    else:
        req.update(ref=args.target, offset=args.offset, length=args.length, binary=args.binary)
    result = rpc(req)
    print(encode(result))
    accepted = {"ok", "queued", "running", "succeeded", "cancellation_requested"}
    return 0 if result.get("status", "ok") in accepted else 1
