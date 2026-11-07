#!/usr/bin/env python3
"""Gate actual desktop effects, retaining a separate compositor lifecycle result."""

import argparse
import json
import re
import struct
from pathlib import Path


def evaluate(root: Path, raw_exit_code: int) -> dict:
    try:
        report = json.loads((root / "desktop-acceptance.json").read_text())
        compositor = json.loads((root / "compositor-exit.json").read_text())["exit_code"]
        serial = (root / "serial.log").read_text()
        checks = report["checks"]
        if report["status"] != "passed" or checks["legacy_stdio"] != "passed":
            raise ValueError("Desktop acceptance did not pass.")
        for name in ("desktop", "launch", "pointer", "screenshot", "keyboard", "close"):
            if checks[name]["status"] != "passed":
                raise ValueError(f"Desktop check {name} did not pass.")
        png = (root / "desktop-acceptance.png").read_bytes()
        if len(png) < 1024 or png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
            raise ValueError("Missing or invalid desktop screenshot.")
        width, height = struct.unpack(">II", png[16:24])
        if width < 320 or height < 200:
            raise ValueError("Desktop screenshot is too small.")
        keyboard = checks["keyboard"]
        marker = root / Path(keyboard["marker"]).name
        if marker.read_text().strip() != keyboard["value"]:
            raise ValueError("Typed command effect was not independently observed.")
        if checks["pointer"]["actual_cursor"] != {"x": 320, "y": 240}:
            raise ValueError("Pointer did not reach the independently checked position.")
    except (OSError, KeyError, TypeError, json.JSONDecodeError, struct.error) as exc:
        raise ValueError(f"Incomplete or invalid desktop evidence: {exc}") from exc

    if raw_exit_code == 0 and compositor == 0:
        return {
            "desktop": "passed",
            "teardown": "passed",
            "raw_exit_code": 0,
            "release_ready": True,
        }
    version = report.get("hyprland_version", "")
    known_trace = re.search(r"Hyprland[^\n]*segfault[^\n]*libaquamarine\.so\.0\.10\.0", serial)
    if (
        raw_exit_code == 2
        and compositor == 139
        and known_trace
        and "Hyprland 0.53.3" in version
        and "Aquamarine: built against 0.10.0" in version
    ):
        return {
            "desktop": "passed",
            "teardown": "known_failure",
            "raw_exit_code": 2,
            "compositor_exit": 139,
            "release_ready": False,
            "reason": (
                "Hyprland 0.53.3/Aquamarine 0.10 teardown segfault; release gate remains open."
            ),
        }
    raise ValueError(f"Unexpected VM result: runner={raw_exit_code}, compositor={compositor}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("raw_exit_code", type=int)
    args = parser.parse_args()
    try:
        result = evaluate(args.results, args.raw_exit_code)
    except ValueError as exc:
        print(json.dumps({"desktop": "failed", "reason": str(exc)}))
        return 1
    (args.results / "ci-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if result["teardown"] == "known_failure":
        print(
            "::warning::Desktop acceptance passed; known compositor teardown failed (139). "
            "Full VM lifecycle is not validated. See raw evidence."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
