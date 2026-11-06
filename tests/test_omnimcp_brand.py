"""The source tree uses one project identity."""

import os
import re
from pathlib import Path


def test_no_previous_project_name_remains():
    root = Path(__file__).resolve().parents[1]
    former = "agent" + "ic" + r"[ _.-]?" + "os"
    pattern = re.compile(former, re.IGNORECASE)
    excluded = {
        ".git", ".venv", ".agent-scratch", ".axiomcode", "__pycache__",
        ".pytest_cache", ".ruff_cache", "dist", "build",
    }
    # Compatibility intentionally retains the previous identity in exactly
    # these three places: translation, its regression tests, and migration help.
    compatibility_files = {
        Path("src/omnimcp/legacy_env.py"),
        Path("tests/test_legacy_env.py"),
        Path("docs/MIGRATION.md"),
    }
    findings = []
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [name for name in subdirs if name not in excluded]
        for name in [*subdirs, *files]:
            path = Path(directory) / name
            relative = path.relative_to(root)
            if pattern.search(str(relative)):
                findings.append(str(relative))
            if path.is_file():
                try:
                    contents = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if relative not in compatibility_files and pattern.search(contents):
                    findings.append(str(relative))
    assert not findings, f"Previous identity still present in {len(findings)} paths: {findings[:8]}"
