"""Report desktop success and compositor teardown separately; missing evidence fails."""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
try:
    desktop = json.loads((root / "desktop-acceptance.json").read_text())
    teardown = json.loads((root / "compositor-exit.json").read_text())
except (OSError, ValueError) as exc:
    print(f"Incomplete runtime evidence: {exc}", file=sys.stderr)
    sys.exit(1)

print(json.dumps({"desktop": desktop.get("status"), "compositor_exit": teardown.get("exit_code")}))
if desktop.get("status") != "passed":
    sys.exit(1)
sys.exit(0 if teardown.get("exit_code") == 0 else 2)
