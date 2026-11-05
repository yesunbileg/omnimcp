#!/usr/bin/env python3
"""Measure schema bytes/local gateway overhead, or evaluate actual paired model traces.

Trace JSONL: task, profile (legacy/compact), model, client, initial_state, success,
components={schema,discovery,arguments,results,screenshots,retries} (actual token counts),
round_trips. Do not substitute byte or character estimates for tokens.
"""

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path

COMPONENTS = {"schema", "discovery", "arguments", "results", "screenshots", "retries"}


def local():
    from agentic_os_mcp import compact, server
    from agentic_os_mcp.core.engine import Engine
    from agentic_os_mcp.core.execution import Context
    from agentic_os_mcp.core.registry import Registry
    from agentic_os_mcp.core.state import Store, encode

    async def schemas():
        result = {}
        for name, app in [("legacy", server.build_app()), ("compact", compact.build_app())]:
            tools = await app.list_tools()
            result[name] = {
                "tools": len(tools),
                "bytes": len(encode([t.model_dump(exclude_none=True) for t in tools]).encode()),
            }
        return result

    result = {"schema": asyncio.run(schemas()), "token_benchmark": "not_measured"}
    with tempfile.TemporaryDirectory(prefix="aos-bench-") as temp:
        store = Store(Path(temp))
        registry = Registry()

        def echo(ctx):
            return {"status": "ok", "value": 1}

        registry.add("bench.echo", echo, readonly=True)
        engine = Engine(registry, store)
        ctx = Context(store)
        overhead = []
        for _ in range(200):
            start = time.perf_counter_ns()
            echo(ctx)
            backend = time.perf_counter_ns() - start
            start = time.perf_counter_ns()
            assert engine.request({"op": "observe", "action": "bench.echo"})["status"] == "ok"
            overhead.append((time.perf_counter_ns() - start - backend) / 1e6)
        overhead.sort()
        result["engine_overhead_ms"] = {
            "p50": statistics.median(overhead),
            "p95": overhead[int(0.95 * len(overhead)) - 1],
            "includes": "validation, dispatch, SQLite event; excludes socket/MCP",
        }
        engine.close()
        store.close()
    return result


def compare(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    pairs = {}
    for row in rows:
        if type(row.get("success")) is not bool:
            raise ValueError("success must be a boolean, not a truthy string.")
        if type(row.get("round_trips")) is not int or row["round_trips"] < 0:
            raise ValueError("round_trips must be a nonnegative integer.")
        if set(row.get("components", {})) != COMPONENTS:
            raise ValueError("Include every actual tool token component in each trace.")
        if any(type(v) is not int or v < 0 for v in row["components"].values()):
            raise ValueError("Token counts must be nonnegative integers.")
        key = (row["task"], row["model"], row["client"], row["initial_state"])
        profiles = pairs.setdefault(key, {})
        if row["profile"] in profiles:
            raise ValueError("Duplicate profile for paired task.")
        profiles[row["profile"]] = row
    expected = {
        r["id"]
        for r in json.loads((Path(__file__).parents[1] / "docs/benchmark-tasks.json").read_text())
    }
    if (
        len(pairs) != len(expected)
        or len({(key[1], key[2]) for key in pairs}) != 1
        or {key[0] for key in pairs} != expected
        or any(set(p) != {"legacy", "compact"} for p in pairs.values())
    ):
        raise ValueError("Need matched baseline and compact traces for all 20 tasks.")
    token_reductions, trip_reductions = [], []
    success = {"legacy": 0, "compact": 0}
    for profiles in pairs.values():
        old, new = profiles["legacy"], profiles["compact"]
        before, after = sum(old["components"].values()), sum(new["components"].values())
        if before <= 0 or old["round_trips"] <= 0:
            raise ValueError("Baseline token counts and round trips must be positive.")
        token_reductions.append(1 - after / before)
        trip_reductions.append(1 - new["round_trips"] / old["round_trips"])
        for name in success:
            success[name] += bool(profiles[name]["success"])
    tokens, trips = statistics.median(token_reductions), statistics.median(trip_reductions)
    return {
        "pairs": len(pairs),
        "median_token_reduction": tokens,
        "median_round_trip_reduction": trips,
        "success": success,
        "trace_gate_passed": tokens >= 0.5
        and trips >= 0.5
        and success["compact"] >= success["legacy"],
        "default_switch_requires": "trace gate plus live correctness and gateway/socket p95 checks",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(args.traces) if args.traces else local()
    value = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(value + "\n")
    print(value)
