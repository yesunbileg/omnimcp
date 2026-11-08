#!/usr/bin/env python3
"""Measure warmed MCP stdio + socket overhead above worker backend time on a private file."""

import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from omnimcp.core.client import rpc


async def measure():
    values = []
    params = StdioServerParameters(
        command=str(Path.home() / ".local/bin/OmniMCP"), args=["--profile", "compact"]
    )
    with tempfile.TemporaryDirectory(prefix="aos-gateway-") as temp:
        path = Path(temp) / "fixture"
        path.write_text("small read fixture")
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            cursor = 0
            while True:
                events = rpc({"op": "events", "since": cursor, "limit": 100})
                cursor = events["cursor"]
                if not events["more"]:
                    break
            for n in range(110):
                start = time.perf_counter_ns()
                result = await session.call_tool(
                    "observe",
                    {"action": "file.read", "params": {"path": str(path)}, "fields": ["revision"]},
                )
                elapsed = (time.perf_counter_ns() - start) / 1e6
                assert not result.isError
                events = rpc({"op": "events", "since": cursor, "limit": 100})
                cursor = events["cursor"]
                backend = [
                    e["duration_ms"] for e in events["items"] if e.get("action") == "file.read"
                ]
                assert len(backend) == 1, events
                if n >= 10:
                    values.append(max(0, elapsed - backend[0]))
    values.sort()
    return {
        "samples": len(values),
        "warmup": 10,
        "p50_ms": statistics.median(values),
        "p95_ms": values[int(0.95 * len(values)) - 1],
        "includes": "MCP stdio/SDK + bridge + Unix socket + validation + SQLite event",
        "backend": "private file.read; measured worker handler duration subtracted",
        "target_p95_below_100ms": values[int(0.95 * len(values)) - 1] < 100,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(asyncio.run(measure()), indent=2)
    print(result)
    if args.output:
        args.output.write_text(result + "\n")
