import json
import subprocess
import sys

import psutil

from omnimcp import cli, safety


def test_stop_refuses_beacon_with_mismatched_birth(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_running_verb_pid", lambda: None)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        path = safety.state_path()
        path.write_text(
            json.dumps(
                {"pid": proc.pid, "create_time": psutil.Process(proc.pid).create_time() - 100}
            )
        )
        assert cli.stop() == 1
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait(timeout=5)
