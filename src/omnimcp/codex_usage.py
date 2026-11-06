"""Read native Codex account quotas without starting a model or reading credentials."""

from __future__ import annotations

import argparse
import json
import math
import os
import selectors
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_MAX_OUTPUT = 1024 * 1024


class _UsageError(Exception):
    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


def _query(executable: str, timeout_s: float) -> dict:
    # This process is ours alone. Never attach to, stop or signal an existing server.
    deadline = time.monotonic() + timeout_s
    with subprocess.Popen(
        [executable, "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as child:
        try:

            def send(message):
                child.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
                child.stdin.flush()

            send(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "omnimcp_usage", "version": "1.0.0"},
                        "capabilities": {"experimentalApi": True},
                    },
                }
            )
            buffer = b""
            total = 0
            initialized = False
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise _UsageError("timeout", "Codex account usage request timed out.")
                    chunk = os.read(child.stdout.fileno(), 65536)
                    if not chunk:
                        raise _UsageError("backend_error", "Codex exited before returning usage.")
                    total += len(chunk)
                    if total > _MAX_OUTPUT:
                        raise _UsageError(
                            "invalid_response", "Codex account response exceeded limit."
                        )
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            message = json.loads(line)
                        except (ValueError, UnicodeError):
                            raise _UsageError(
                                "invalid_response", "Invalid Codex account response."
                            ) from None
                        if not isinstance(message, dict):
                            raise _UsageError("invalid_response", "Invalid Codex account response.")
                        wanted = 2 if initialized else 1
                        if message.get("id") != wanted:
                            continue  # unrelated notifications carry no account result
                        if "error" in message:
                            error = message["error"]
                            code = error.get("code") if isinstance(error, dict) else None
                            status = (
                                "auth_required" if code in (401, 403, -32001) else "backend_error"
                            )
                            # Never forward backend messages, stderr or arbitrary fields.
                            raise _UsageError(status, "Codex could not read native account limits.")
                        if "result" not in message:
                            raise _UsageError("invalid_response", "Missing Codex account result.")
                        if not initialized:
                            if not isinstance(message["result"], dict):
                                raise _UsageError(
                                    "invalid_response", "Invalid initialization result."
                                )
                            send({"method": "initialized"})
                            send({"id": 2, "method": "account/rateLimits/read"})
                            initialized = True
                        else:
                            return message["result"]
        finally:
            # Reap on success, protocol failure, timeout and caller cancellation.
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


def _number(value):
    try:
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )
    except OverflowError:
        return False


def _normalize(raw: dict, zone) -> list[dict]:
    def invalid():
        return _UsageError("invalid_response", "Invalid Codex rate-limit fields.")

    if not isinstance(raw, dict):
        raise invalid()
    buckets = raw.get("rateLimitsByLimitId")
    if buckets is None:
        buckets = {}
    if not isinstance(buckets, dict) or len(buckets) > 100:
        raise invalid()
    buckets = dict(buckets)
    fallback = raw.get("rateLimits")
    if fallback is not None:
        if not isinstance(fallback, dict):
            raise invalid()
        key = fallback.get("limitId") or "codex"
        if not isinstance(key, str):
            raise invalid()
        buckets.setdefault(key, fallback)
    if not buckets:
        raise _UsageError("unavailable", "Native account quota windows are unavailable.")
    limits = []
    for key, bucket in buckets.items():
        if not isinstance(key, str) or len(key) > 200 or not isinstance(bucket, dict):
            raise invalid()
        plan = bucket.get("planType")
        if plan is not None and (not isinstance(plan, str) or len(plan) > 100):
            raise invalid()
        windows = []
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if window is None:
                continue
            if not isinstance(window, dict):
                raise invalid()
            used, minutes, reset = (
                window.get("usedPercent"),
                window.get("windowDurationMins"),
                window.get("resetsAt"),
            )
            if not _number(used) or not 0 <= used <= 100:
                raise invalid()
            if minutes is not None and (not _number(minutes) or minutes <= 0):
                raise invalid()
            utc = local = None
            if reset is not None:
                if not _number(reset):
                    raise invalid()
                try:
                    timestamp = datetime.fromtimestamp(reset, UTC)
                    utc = timestamp.isoformat()
                    local = timestamp.astimezone(zone).isoformat()
                except (ValueError, OverflowError, OSError):
                    raise invalid() from None
            windows.append(
                {
                    "kind": {300: "five_hour", 10080: "weekly"}.get(minutes, "other"),
                    "window_minutes": minutes,
                    "used_percent": used,
                    "remaining_percent": 100 - used,
                    "resets_at": reset,
                    "reset_utc": utc,
                    "reset_local": local,
                }
            )
        limits.append({"limit_id": key, "plan_type": plan, "windows": windows})
    return limits


def read_usage(timeout_s: float = 25, timezone: str = "") -> dict:
    """Read native account quotas; timeout 0..60 seconds, optional IANA timezone.

    Returns status, checked_at, timezone and per-limit windows with used/remaining
    percentages and UTC/local reset times. Missing windows stay absent. Uses the
    installed codex and inherited native profile/login; no generation or MCP calls.
    """
    try:
        if not _number(timeout_s) or not 0 < timeout_s <= 60:
            raise _UsageError("invalid_params", "timeout_s must be within (0,60].")
        if not isinstance(timezone, str) or len(timezone) > 100:
            raise _UsageError("invalid_params", "timezone must be an IANA timezone or empty.")
        try:
            zone = ZoneInfo(timezone) if timezone else None
        except (ValueError, ZoneInfoNotFoundError):
            raise _UsageError("invalid_params", "Unknown IANA timezone.") from None
        executable = shutil.which("codex")
        local = Path.home() / ".local/bin/codex"
        if not executable and local.is_file() and os.access(local, os.X_OK):
            executable = str(local)
        if not executable:
            raise _UsageError("missing_dependency", "Install and sign in to the Codex CLI first.")
        raw = _query(executable, timeout_s)
        limits = _normalize(raw, zone)
        return {
            "status": "ok",
            "checked_at": datetime.now(UTC).isoformat(),
            "timezone": timezone or "system",
            "limits": limits,
        }
    except _UsageError as exc:
        return {"status": exc.status, "message": str(exc)}
    except OSError:
        return {"status": "backend_error", "message": "Could not run the installed Codex CLI."}


def codex_usage(timeout_s: float = 25, timezone: str = "") -> str:
    """Read Codex account usage: 5-hour/weekly used and remaining %, reset times.

    Uses native login without model generation or credentials copying. Optional
    IANA timezone (e.g. Asia/Ulaanbaatar); empty uses system local time. Missing
    windows remain absent; other durations are labeled other. No desktop needed.
    """
    return json.dumps(read_usage(timeout_s, timezone), ensure_ascii=False, separators=(",", ":"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="omnimcp codex-usage")
    parser.add_argument("--timeout-s", type=float, default=25)
    parser.add_argument("--timezone", default="")
    args = parser.parse_args(argv)
    result = read_usage(args.timeout_s, args.timezone)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
