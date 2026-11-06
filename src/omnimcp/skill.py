"""`omnimcp skill`: the Agent Skill that teaches a shell-driven agent the verbs.

The skill ships inside the package (built from `skills/omnimcp/` in the
repository), so the copy an agent reads always describes the verbs the
installed binary has. `install` puts one canonical copy under
~/.agents/skills, the directory the agent-skills convention shares between
agents, and links it into each agent's own skills directory that exists on
this machine, the same loop Omarchy's provisioner runs for its skills.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

NAME = "omnimcp"
CANONICAL = "~/.agents/skills"

# agent -> its user-global skills directories. A link is only made when the
# agent's own config directory (the parent) already exists, so an install
# never scatters ~/.cursor, ~/.copilot and friends over a machine that runs
# none of them; naming an agent with --agent creates it regardless.
AGENT_DIRS: dict[str, tuple[str, ...]] = {
    "claude-code": ("~/.claude/skills",),
    "codex": ("~/.codex/skills",),
    "pi": ("~/.pi/agent/skills",),
    "hermes": ("~/.hermes/skills",),
    "gemini": ("~/.gemini/skills",),
    "antigravity": ("~/.gemini/antigravity/skills", "~/.gemini/config/skills"),
    "opencode": ("~/.config/opencode/skills",),
    "openclaw": ("~/.openclaw/skills",),
    "cursor": ("~/.cursor/skills",),
    "copilot": ("~/.copilot/skills",),
}

_NAME_LINE = re.compile(r"^name:\s*omnimcp\s*$", re.M)


def packaged_dir() -> Path | None:
    """The skill directory this build carries: `omnimcp/skill/` in an
    installed wheel, `skills/omnimcp/` in a source checkout."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "skill", here.parent.parent / "skills" / NAME):
        if (candidate / "SKILL.md").is_file():
            return candidate
    return None


def _ours(target: Path) -> bool:
    """Only a directory holding omnimcp's own SKILL.md may be replaced or
    removed; anything else at that path belongs to the user."""
    try:
        head = (target / "SKILL.md").read_text(errors="replace")[:4000]
    except OSError:
        return False
    return bool(_NAME_LINE.search(head))


def _remove(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        shutil.rmtree(target)


def _dirs_for(agent: str) -> list[Path]:
    dirs = [Path(d).expanduser() for d in AGENT_DIRS[agent]]
    if agent == "hermes":  # every profile has its own skills directory
        profiles = Path("~/.hermes/profiles").expanduser()
        if profiles.is_dir():
            dirs.extend(p / "skills" for p in sorted(profiles.iterdir()) if p.is_dir())
    return dirs


def install(agents: list[str], copy: bool) -> int:
    src = packaged_dir()
    if src is None:
        print("omnimcp: error: this build carries no skill directory", file=sys.stderr)
        return 1
    unknown = sorted(set(agents) - set(AGENT_DIRS))
    if unknown:
        print(
            f"omnimcp: usage: unknown agent {', '.join(unknown)} "
            f"(known: {', '.join(sorted(AGENT_DIRS))})",
            file=sys.stderr,
        )
        return 2
    canonical = Path(CANONICAL).expanduser() / NAME
    if canonical.exists() or canonical.is_symlink():
        if not _ours(canonical):
            print(
                f"omnimcp: error: {canonical} exists and is not omnimcp's skill; "
                "move it aside first",
                file=sys.stderr,
            )
            return 1
        _remove(canonical)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, canonical)
    print(f"installed {canonical}")

    explicit = bool(agents)
    linked = 0
    for agent in sorted(agents or AGENT_DIRS):
        for base in _dirs_for(agent):
            if not explicit and not base.parent.exists():
                continue  # that agent is not on this machine
            base.mkdir(parents=True, exist_ok=True)
            target = base / NAME
            if target.exists() or target.is_symlink():
                if target.is_symlink() and target.resolve() == canonical.resolve() and not copy:
                    print(f"  {agent}: {target} (already linked)")
                    linked += 1
                    continue
                if not _ours(target):
                    print(f"  {agent}: {target} exists and is not omnimcp's, left alone")
                    continue
                _remove(target)
            if copy:
                shutil.copytree(canonical, target)
            else:
                target.symlink_to(canonical)
            print(f"  {agent}: {target}")
            linked += 1
    if not linked:
        print(
            "  no agent skill directories found; name one to create it: "
            "omnimcp skill install --agent claude-code"
        )
    return 0


def uninstall() -> int:
    canonical = Path(CANONICAL).expanduser() / NAME
    removed = 0
    for agent in sorted(AGENT_DIRS):
        for base in _dirs_for(agent):
            target = base / NAME
            if not (target.exists() or target.is_symlink()):
                continue
            points_here = target.is_symlink() and target.resolve() == canonical.resolve()
            if points_here or _ours(target):
                _remove(target)
                print(f"removed {target}")
                removed += 1
    if canonical.is_symlink() or (canonical.exists() and _ours(canonical)):
        _remove(canonical)
        print(f"removed {canonical}")
        removed += 1
    if not removed:
        print("nothing to remove")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="omnimcp skill",
        description="The Agent Skill that teaches shell-driven agents the omnimcp verbs.",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="COMMAND")
    sub.required = True
    sub.add_parser("path", help="print the packaged skill directory")
    ins = sub.add_parser(
        "install",
        help=f"copy the skill to {CANONICAL}/{NAME} and link it into each agent's skills",
    )
    ins.add_argument(
        "--agent",
        action="append",
        default=[],
        metavar="NAME",
        help=f"only these agents, created if absent ({', '.join(sorted(AGENT_DIRS))})",
    )
    ins.add_argument("--copy", action="store_true", help="copy instead of symlinking")
    sub.add_parser("uninstall", help="remove the links and the canonical copy")
    args = parser.parse_args(argv)
    if args.cmd == "path":
        src = packaged_dir()
        if src is None:
            print("omnimcp: error: this build carries no skill directory", file=sys.stderr)
            return 1
        print(src)
        return 0
    if args.cmd == "install":
        return install(args.agent, args.copy)
    return uninstall()
