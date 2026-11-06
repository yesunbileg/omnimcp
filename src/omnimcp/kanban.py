"""A single configured Obsidian Kanban file, with revision-checked writes.

No database, desktop interaction, background worker, or task execution. Every
read goes to disk. MCP writers share an advisory lock; external editors do not,
so writes also compare the original bytes immediately before atomic replace.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import re
import stat
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from omnimcp import journal

ENV = "OMNIMCP_KANBAN_FILE"
MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 16_000
_CARD = re.compile(r"^- \[([ xX])\] (.*)$")
_ANCHOR = re.compile(r"\s+\^([A-Za-z0-9-]+)\s*$")
_ON = {"1", "true", "yes", "on"}


def configured() -> bool:
    return bool(os.environ.get(ENV, "").strip())


def _path() -> Path:
    value = os.environ.get(ENV, "").strip()
    if not value:
        raise ValueError(f"Kanban is not configured: set {ENV} to an existing board file")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{ENV} must be an absolute path")
    if path.suffix.lower() != ".md":
        raise ValueError("Kanban requires a .md board file")
    return path


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _snapshot(path: Path) -> tuple[bytes, os.stat_result]:
    # Never follow a swapped-in symlink or block on a FIFO.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Kanban board must be a regular file")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Kanban board exceeds {MAX_BYTES} bytes")
    return raw, info


@dataclass
class Card:
    start: int
    end: int
    checked: bool
    column: str
    id: str = ""
    text: str = ""
    anchored: bool = False


@dataclass
class Column:
    name: str
    start: int
    end: int
    cards: list[Card] = field(default_factory=list)


class Board:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.revision = _digest(raw)
        text = raw.decode("utf-8")
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.lines = text.splitlines(keepends=True)
        self.columns: list[Column] = []
        self.cards: list[Card] = []
        if not self.lines or self.lines[0].lstrip("\ufeff").strip() != "---":
            raise ValueError("Not an Obsidian Kanban board: missing YAML frontmatter")
        try:
            end = next(i for i in range(1, len(self.lines)) if self.lines[i].strip() == "---")
        except StopIteration as exc:
            raise ValueError("Kanban frontmatter is not closed") from exc
        frontmatter = "".join(self.lines[1:end])
        if not re.search(r"^kanban-plugin:\s*['\"]?(?:board|basic)['\"]?\s*$",
                         frontmatter, re.MULTILINE):
            raise ValueError("Not an Obsidian Kanban board: kanban-plugin must be board or basic")

        column: Column | None = None
        card: Card | None = None
        fence = ""
        comment = False
        stop = len(self.lines)
        for i in range(end + 1, len(self.lines)):
            line = self.lines[i].rstrip("\r\n")
            # Settings and the plugin's archive are opaque, never active columns.
            if not fence and not comment and (
                line.startswith("%% kanban:settings") or line.strip() == "***"
            ):
                stop = i
                break
            if card and line.startswith(("\t", "  ")):
                card.end = i + 1
                continue
            card = None
            if line.startswith("%%"):
                if line.count("%%") % 2:
                    comment = not comment
                continue
            if comment:
                continue
            marker = re.match(r"^(`{3,}|~{3,})", line)
            if marker:
                if not fence:
                    fence = marker[1]
                elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                    fence = ""
                continue
            if fence:
                continue
            if line.startswith("## "):
                name = line[3:].strip()
                if not name or any(c.name == name for c in self.columns):
                    raise ValueError("Kanban columns must have unique, non-empty names")
                if column:
                    column.end = i
                column = Column(name, i, len(self.lines))
                self.columns.append(column)
                continue
            match = _CARD.match(line)
            if match and column:
                card = Card(i, i + 1, match[1].lower() == "x", column.name)
                column.cards.append(card)
                self.cards.append(card)
        if column:
            column.end = stop
        if not self.columns:
            raise ValueError("Kanban board has no named ## columns")
        seen: set[str] = set()
        for item in self.cards:
            body = _CARD.fullmatch(self.lines[item.start].rstrip("\r\n"))[2]
            continuation = [re.sub(r"^(?:\t| {2,4})", "", line.rstrip("\r\n"))
                            for line in self.lines[item.start + 1:item.end]]
            body = "\n".join([body, *continuation])
            anchor = _ANCHOR.search(body)
            if anchor:
                item.id = anchor[1]
                item.anchored = True
                body = body[:anchor.start()]
            else:
                # Legacy IDs are valid only with the matching board revision.
                digest = _digest("".join(self.lines[item.start:item.end]).encode())[:16]
                item.id = f"legacy-{item.start + 1}-{digest}"
            if item.id in seen:
                raise ValueError(f"Duplicate Kanban task ID: {item.id}")
            seen.add(item.id)
            item.text = body

    def column(self, name: str) -> Column:
        for column in self.columns:
            if column.name == name:
                return column
        raise ValueError(f"Unknown column {name!r}; use kanban_read to list exact column names")

    def card(self, task_id: str) -> Card:
        for card in self.cards:
            if card.id == task_id:
                return card
        raise ValueError("Task ID not found; call kanban_read again")

    @staticmethod
    def view(card: Card, *, full: bool = False) -> dict[str, Any]:
        limit = MAX_TEXT if full else 1200
        return {"id": card.id, "column": card.column, "checked": card.checked,
                "text": card.text[:limit], "text_truncated": len(card.text) > limit,
                "stable_id": card.anchored}


def read(column: str = "", query: str = "", task_id: str = "",
         limit: int = 50, offset: int = 0) -> dict[str, Any]:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit must be 1..100 and offset must be non-negative")
    path = _path()
    raw, _ = _snapshot(path)
    board = Board(raw)
    if column:
        board.column(column)
    cards = [board.card(task_id)] if task_id else board.cards
    cards = [card for card in cards if (not column or card.column == column)
             and (not query or query.casefold() in card.text.casefold())]
    page = cards[offset:offset + limit]
    return {"path": str(path), "revision": board.revision,
            "columns": [{"name": c.name, "count": len(c.cards)} for c in board.columns],
            "tasks": [board.view(c, full=bool(task_id)) for c in page],
            "total": len(cards), "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(cards) else None}


@contextlib.contextmanager
def _lock(path: Path) -> Iterator[None]:
    root = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    directory = root / f"omnimcp-kanban-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Kanban lock directory must be private and owned by the current user")
    lock_path = directory / (_digest(os.fsencode(path.resolve())) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+b") as stream:
        # Fail promptly rather than waiting indefinitely for another client.
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Kanban board is busy; read its latest revision and retry") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value or len(value) > MAX_TEXT or "\x00" in value:
        raise ValueError(f"Task text must contain 1..{MAX_TEXT} characters and no NUL")
    if re.search(r"(?:^|\s)\^[A-Za-z0-9-]+(?:\s|$)", value):
        raise ValueError("Task text must not supply a block ID; the server manages task IDs")
    return value


def _render(text: str, task_id: str, checked: bool, newline: str) -> list[str]:
    parts = text.split("\n")
    lines = [f"- [{'x' if checked else ' '}] {parts[0]}{newline}"]
    lines.extend(f"\t{part}{newline}" for part in parts[1:])
    lines[-1] = lines[-1].rstrip("\r\n") + f" ^{task_id}" + newline
    return lines


def _insert(board: Board, column: str, card_lines: list[str]) -> list[str]:
    target = board.column(column)
    lines = board.lines.copy()
    pos = target.end
    while pos > target.start + 1 and not lines[pos - 1].strip():
        pos -= 1
    if pos and not lines[pos - 1].endswith("\n"):
        lines[pos - 1] += board.newline
    lines[pos:pos] = [board.newline, *card_lines, board.newline]
    return lines


def _save(path: Path, original: bytes, info: os.stat_result, updated: bytes) -> None:
    if len(updated) > MAX_BYTES:
        raise ValueError("Updated Kanban board would exceed the size limit")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.omnimcp-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        current, current_info = _snapshot(path)
        before = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns)
        now = (current_info.st_dev, current_info.st_ino,
               current_info.st_mtime_ns, current_info.st_ctime_ns)
        if current != original or before != now:
            raise ValueError(
                "Kanban revision conflict: the file changed; read again before writing"
            )
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


def _mutate(expected_revision: str,
            change: Callable[[Board], tuple[list[str], str]]) -> dict[str, Any]:
    if os.environ.get("OMNIMCP_READONLY", "").lower() in _ON:
        raise ValueError("Kanban writes are disabled in OMNIMCP_READONLY mode")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_revision):
        raise ValueError("expected_revision must be the revision returned by kanban_read")
    path = _path()
    dry_run = journal.dry_run()
    with contextlib.nullcontext() if dry_run else _lock(path):
        original, info = _snapshot(path)
        board = Board(original)
        if board.revision != expected_revision:
            raise ValueError("Kanban revision conflict: call kanban_read and reconsider the change")
        lines, task_id = change(board)
        updated = "".join(lines).encode("utf-8")
        parsed = Board(updated)  # malformed output must never replace the board
        result = {"path": str(path), "revision": board.revision if dry_run else parsed.revision,
                  "task": parsed.view(parsed.card(task_id), full=True), "dry_run": dry_run}
        if len(updated) > MAX_BYTES:
            raise ValueError("Updated Kanban board would exceed the size limit")
        if dry_run:
            result["would_revision"] = parsed.revision
        elif updated != original:
            _save(path, original, info, updated)
        return result


def add(column: str, text: str, expected_revision: str) -> dict[str, Any]:
    text = _text(text)

    def change(board: Board) -> tuple[list[str], str]:
        task_id = "kanban-" + uuid.uuid4().hex[:16]
        return _insert(board, column, _render(text, task_id, False, board.newline)), task_id

    return _mutate(expected_revision, change)


def update(task_id: str, expected_revision: str, text: str | None = None,
           column: str | None = None, checked: bool | None = None,
           append_text: str | None = None) -> dict[str, Any]:
    if text is not None and append_text is not None:
        raise ValueError("Supply text or append_text, not both")
    if text is None and column is None and checked is None and append_text is None:
        raise ValueError("Supply text, append_text, column, or checked to update a task")
    if text is not None:
        text = _text(text)
    if append_text is not None:
        append_text = _text(append_text)

    def change(board: Board) -> tuple[list[str], str]:
        card = board.card(task_id)
        target = card.column if column is None else column
        board.column(target)
        stable_id = card.id if card.anchored else "kanban-" + uuid.uuid4().hex[:16]
        replacement = text
        if append_text is not None:
            replacement = _text(card.text + "\n" + append_text)
        if replacement is not None:
            card_lines = _render(replacement, stable_id,
                                 card.checked if checked is None else checked,
                                 board.newline)
        else:
            card_lines = board.lines[card.start:card.end].copy()
            if checked is not None:
                card_lines[0] = card_lines[0][:3] + ("x" if checked else " ") + card_lines[0][4:]
            if not card.anchored:
                card_lines[-1] = (card_lines[-1].rstrip("\r\n")
                                  + f" ^{stable_id}" + board.newline)
        if target == card.column:
            lines = board.lines[:card.start] + card_lines + board.lines[card.end:]
        else:
            remainder = Board("".join(board.lines[:card.start] + board.lines[card.end:]).encode())
            lines = _insert(remainder, target, card_lines)
        return lines, stable_id

    return _mutate(expected_revision, change)


def wait(revision: str, timeout_s: float = 15) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", revision):
        raise ValueError("revision must come from kanban_read")
    if not 0 <= timeout_s <= 30:
        raise ValueError("timeout_s must be 0..30")
    path = _path()
    deadline = time.monotonic() + timeout_s
    while True:
        raw, _ = _snapshot(path)
        current = _digest(raw)
        if current != revision:
            return {"path": str(path), "revision": current, "changed": True}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"path": str(path), "revision": current, "changed": False}
        time.sleep(min(0.25, remaining))
