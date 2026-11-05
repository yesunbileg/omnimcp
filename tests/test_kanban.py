"""Board mutations use isolated files, never the user's live task board."""

import asyncio
import os
import threading

import pytest

from agentic_os_mcp import kanban, server

BOARD = """---
kanban-plugin: board
custom: keep
---

## Хийх

- [ ] **Товч хийх** — Codex
- [ ] Keep this exactly ^existing-id

## Хийж байгаа

- [ ] Other card

## Дууссан

- [x] Earlier work

%% kanban:settings
```
{"kanban-plugin":"board","list-collapse":[false,false,false]}
```
%%
"""


@pytest.fixture
def board(tmp_path, monkeypatch):
    path = tmp_path / "kanban.md"
    path.write_bytes(BOARD.encode())
    monkeypatch.setenv(kanban.ENV, str(path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return path


def test_read_unicode_ids_filter_pagination_and_no_write(board):
    original = board.read_bytes()
    result = kanban.read()
    assert result["columns"] == [
        {"name": "Хийх", "count": 2}, {"name": "Хийж байгаа", "count": 1},
        {"name": "Дууссан", "count": 1},
    ]
    assert result["tasks"][0]["id"].startswith("legacy-")
    assert result["tasks"][1]["id"] == "existing-id"
    assert kanban.read(query="codex")["total"] == 1
    assert kanban.read(column="Хийх", limit=1)["next_offset"] == 1
    assert kanban.read(column="Хийх", limit=1, offset=1)["next_offset"] is None
    assert board.read_bytes() == original


def test_add_move_and_complete_preserve_other_content(board):
    before = kanban.read()
    added = kanban.add("Хийх", "Шинэ ажил\nAcceptance: цонх нээгдэнэ", before["revision"])
    assert added["task"]["stable_id"]
    assert added["task"]["text"] == "Шинэ ажил\nAcceptance: цонх нээгдэнэ"
    moved = kanban.update(added["task"]["id"], added["revision"], column="Хийж байгаа")
    assert moved["task"]["id"] == added["task"]["id"]
    assert moved["task"]["checked"] is False
    done = kanban.update(moved["task"]["id"], moved["revision"], column="Дууссан", checked=True)
    assert done["task"]["checked"] is True
    assert kanban.read(task_id=done["task"]["id"])["tasks"][0] == done["task"]
    raw = board.read_text()
    assert "- [ ] Keep this exactly ^existing-id\n" in raw
    assert raw.split("%% kanban:settings", 1)[1] == BOARD.split("%% kanban:settings", 1)[1]
    assert raw.startswith(BOARD.split("## Хийх", 1)[0])


def test_first_edit_gives_legacy_card_a_stable_id(board):
    before = kanban.read()
    card = before["tasks"][0]
    moved = kanban.update(card["id"], before["revision"], column="Хийж байгаа")
    assert moved["task"]["id"].startswith("kanban-")
    assert moved["task"]["text"] == card["text"]
    edited = kanban.update(moved["task"]["id"], moved["revision"], text="Шалгасан товч")
    assert edited["task"]["id"] == moved["task"]["id"]


def test_crlf_multiline_and_checked_preserved(board):
    board.write_bytes(BOARD.replace("\n", "\r\n").encode())
    before = kanban.read()
    card = before["tasks"][-1]
    moved = kanban.update(card["id"], before["revision"], column="Хийх")
    assert moved["task"]["checked"] is True
    added = kanban.add("Хийх", "First\n## not a column\n- [ ] not a separate card",
                       moved["revision"])
    assert kanban.read(task_id=added["task"]["id"])["total"] == 1
    raw = board.read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert len(kanban.read()["columns"]) == 3


def test_stale_revision_does_not_overwrite_external_edit(board):
    revision = kanban.read()["revision"]
    external = BOARD.replace("Other card", "Human changed this")
    board.write_text(external)
    with pytest.raises(ValueError, match="revision conflict"):
        kanban.add("Хийх", "Agent card", revision)
    assert board.read_text() == external
    assert not list(board.parent.glob("*.tmp"))


def test_external_edit_during_save_is_detected(board, monkeypatch):
    before = kanban.read()
    real_mkstemp = kanban.tempfile.mkstemp
    external = BOARD.replace("Other card", "Human edit while agent prepares write")

    def changed(*args, **kwargs):
        result = real_mkstemp(*args, **kwargs)
        board.write_text(external)
        return result

    monkeypatch.setattr(kanban.tempfile, "mkstemp", changed)
    with pytest.raises(ValueError, match="revision conflict"):
        kanban.add("Хийх", "Agent card", before["revision"])
    assert board.read_text() == external
    assert not list(board.parent.glob("*.tmp"))


def test_two_agents_cannot_claim_same_revision(board):
    before = kanban.read()
    barrier = threading.Barrier(2)
    results = []

    def claim():
        barrier.wait()
        try:
            results.append(kanban.update(before["tasks"][0]["id"], before["revision"],
                                          column="Хийж байгаа"))
        except ValueError as error:
            results.append(error)

    workers = [threading.Thread(target=claim) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)
        assert not worker.is_alive()
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert kanban.read(column="Хийж байгаа")["total"] == 2


def test_readonly_and_dry_run_preserve_board(board, monkeypatch):
    before = kanban.read()
    monkeypatch.setenv("AGENTIC_OS_READONLY", "1")
    with pytest.raises(ValueError, match="READONLY"):
        kanban.add("Хийх", "Not allowed", before["revision"])
    monkeypatch.delenv("AGENTIC_OS_READONLY")
    monkeypatch.setenv("AGENTIC_OS_DRYRUN", "1")
    preview = kanban.add("Хийх", "Preview", before["revision"])
    assert preview["dry_run"] is True
    assert preview["revision"] == before["revision"]
    assert preview["would_revision"] != before["revision"]
    assert board.read_text() == BOARD
    assert list(board.parent.iterdir()) == [board]


def test_permissions_preserved(board):
    os.chmod(board, 0o640)
    kanban.add("Хийх", "New task", kanban.read()["revision"])
    assert board.stat().st_mode & 0o777 == 0o640


def test_wait_returns_changes_and_timeout(board):
    revision = kanban.read()["revision"]
    assert kanban.wait(revision, 0)["changed"] is False
    board.write_text(BOARD.replace("Other card", "Edited elsewhere"))
    assert kanban.wait(revision, 0)["changed"] is True


def test_settings_archive_comments_and_fences_not_tasks(board):
    data = BOARD.replace("## Хийх",
                         "```md\n## Fake\n- [ ] fake\n```\n\n%%\n## Hidden\n%%\n\n## Хийх")
    data = data.replace("%% kanban:settings",
                         "***\n## Archive\n- [x] old archived task\n\n%% kanban:settings")
    board.write_text(data)
    assert len(kanban.read()["columns"]) == 3
    assert kanban.read()["total"] == 4
    kanban.add("Дууссан", "Another task", kanban.read()["revision"])
    assert board.read_text().split("***", 1)[1] == data.split("***", 1)[1]


@pytest.mark.parametrize("replacement,match", [
    ("## Хийх", "unique"), ("## ", "non-empty"),
])
def test_ambiguous_column_names_refused(board, replacement, match):
    board.write_text(BOARD.replace("## Хийж байгаа", replacement))
    with pytest.raises(ValueError, match=match):
        kanban.read()


def test_symlinks_and_nonboards_refused(board):
    original = board.read_bytes()
    target = board.with_name("actual.md")
    board.rename(target)
    board.symlink_to(target)
    with pytest.raises(OSError):
        kanban.read()
    assert target.read_bytes() == original
    board.unlink()
    board.write_text("# Plain note\n")
    with pytest.raises(ValueError, match="frontmatter"):
        kanban.read()


def test_duplicate_task_id_and_size_limit_refused(board, monkeypatch):
    board.write_text(BOARD.replace("Other card", "Other card ^existing-id"))
    with pytest.raises(ValueError, match="Duplicate"):
        kanban.read()
    monkeypatch.setattr(kanban, "MAX_BYTES", 12)
    with pytest.raises(ValueError, match="exceeds"):
        kanban.read()


def test_text_validation_and_missing_column_cannot_change_board(board):
    revision = kanban.read()["revision"]
    for text in ["", "a ^injected-id", "nul\x00byte"]:
        with pytest.raises(ValueError):
            kanban.add("Хийх", text, revision)
    with pytest.raises(ValueError, match="Unknown column"):
        kanban.add("Missing", "Good text", revision)
    assert board.read_text() == BOARD


def test_mcp_registration_opt_in_readonly_and_serialization(board, monkeypatch):
    async def exercise():
        app = server.build_app()
        tools = {tool.name: tool for tool in await app.list_tools()}
        assert {"kanban_read", "kanban_add", "kanban_update", "kanban_wait"} <= tools.keys()
        assert tools["kanban_read"].annotations.readOnlyHint is True
        assert tools["kanban_update"].annotations.destructiveHint is True
        result = await app.call_tool("kanban_read", {})
        assert "Хийх" in str(result)
        assert "kanban_read, not desktop" in app.instructions
        monkeypatch.setattr(server, "READONLY", True)
        readonly = {tool.name for tool in await server.build_app().list_tools()}
        assert "kanban_read" in readonly and "kanban_wait" in readonly
        assert "kanban_add" not in readonly and "kanban_update" not in readonly
        monkeypatch.delenv(kanban.ENV)
        disabled = {tool.name for tool in await server.build_app().list_tools()}
        assert not any(name.startswith("kanban_") for name in disabled)

    asyncio.run(exercise())


@pytest.mark.parametrize("crlf", [False, True])
def test_append_result_moves_and_checks_without_replacing_instructions(board, crlf):
    if crlf:
        board.write_bytes(BOARD.replace("\n", "\r\n").encode())
    before = kanban.read()
    card = before["tasks"][0]
    result = kanban.update(card["id"], before["revision"], column="Дууссан",
                           checked=True, append_text="Үр дүн: шалгав.\nURL: https://example.org/")
    assert result["task"]["text"] == card["text"] + (
        "\nҮр дүн: шалгав.\nURL: https://example.org/")
    assert result["task"]["checked"] is True
    assert result["task"]["column"] == "Дууссан"
    assert kanban.read(task_id=result["task"]["id"])["tasks"][0] == result["task"]
    raw = board.read_bytes()
    if crlf:
        assert b"\n" not in raw.replace(b"\r\n", b"")
    assert raw.count(("^" + result["task"]["id"]).encode()) == 1
    assert "- [ ] Keep this exactly ^existing-id" in raw.decode()


def test_append_validation_conflicts_and_dry_run_cannot_lose_content(board, monkeypatch):
    before = kanban.read()
    task_id = before["tasks"][0]["id"]
    for args in ({"text": "Replacement", "append_text": "Result"},
                 {"append_text": ""}, {"append_text": "Result ^injected-id"},
                 {"append_text": "x" * kanban.MAX_TEXT}):
        with pytest.raises(ValueError):
            kanban.update(task_id, before["revision"], **args)
    assert board.read_text() == BOARD
    monkeypatch.setenv("AGENTIC_OS_DRYRUN", "1")
    preview = kanban.update(task_id, before["revision"], append_text="Preview")
    assert preview["dry_run"] and preview["task"]["text"].endswith("\nPreview")
    assert board.read_text() == BOARD
    monkeypatch.delenv("AGENTIC_OS_DRYRUN")
    external = BOARD.replace("Other card", "Human edited")
    board.write_text(external)
    with pytest.raises(ValueError, match="revision conflict"):
        kanban.update(task_id, before["revision"], append_text="Result")
    assert board.read_text() == external
