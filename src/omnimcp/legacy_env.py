"""Translate pre-rename environment variables before configuration is read."""

import os
import sys


def migrate_legacy_env() -> None:
    for old, value in tuple(os.environ.items()):
        if old.startswith("AGENTIC_OS_"):
            new = "OMNIMCP_" + old[len("AGENTIC_OS_"):]
            os.environ.setdefault(new, value)
            print(f"omnimcp: {old!a} is deprecated; use {new!a}", file=sys.stderr)
