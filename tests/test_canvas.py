"""Semantic Canvas contract, preservation, and the real MCP wire."""

import asyncio
import copy
import importlib
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from omnimcp import canvas, server, trust, verbs


@pytest.fixture
def saved(tmp_path):
    doc = {
        "nodes": [
            {
                "id": "a-long-persistent-id-1",
                "type": "group",
                "label": "Plan",
                "color": "6",
                "x": -20,
                "y": -20,
                "width": 1000,
                "height": 800,
                "background": "secret-background.png",
                "plugin": {"keep": True},
            },
            {
                "id": "a-long-persistent-id-2",
                "type": "text",
                "text": "# Санаа\n" + "内容" * 600,
                "color": "1",
                "x": 10,
                "y": 20,
                "width": 200,
                "height": 100,
            },
            {
                "id": "a-long-persistent-id-3",
                "type": "file",
                "file": "Notes/Test.md",
                "subpath": "#Heading",
                "x": 300,
                "y": 20,
                "width": 200,
                "height": 100,
            },
            {
                "id": "a-long-persistent-id-4",
                "type": "link",
                "url": "https://example.org",
                "x": 300,
                "y": 200,
                "width": 200,
                "height": 100,
            },
        ],
        "edges": [
            {
                "id": "edge-long-persistent-id-1",
                "fromNode": "a-long-persistent-id-2",
                "toNode": "a-long-persistent-id-3",
                "label": "хийх",
                "color": "4",
                "fromSide": "right",
                "toSide": "left",
                "plugin": 42,
            },
        ],
        "plugin": {"preserve": [1, 2, 3]},
    }
    path = tmp_path / "Test.canvas"
    path.write_text(json.dumps(doc, ensure_ascii=False))
    return path, doc


def test_read_returns_all_nine_semantic_fields_but_no_geometry_or_long_ids(saved):
    path, doc = saved
    raw = path.read_bytes()
    view = canvas.run(str(path))
    group, text, file, link = view["cards"]
    assert text == {
        "id": "n2",
        "type": "text",
        "title": "Санаа",
        "text": doc["nodes"][1]["text"],
        "color": "red",
        "groups": ["n1"],
    }
    assert group["label"] == "Plan" and group["color"] == "purple"
    assert file["file"] == "Notes/Test.md" and file["subpath"] == "#Heading"
    assert link["url"] == "https://example.org"
    assert view["connections"] == [
        {
            "id": "e1",
            "from": "n2",
            "to": "n3",
            "direction": "forward",
            "label": "хийх",
            "color": "green",
        }
    ]
    dumped = json.dumps(view)
    for hidden in (
        '"x":',
        '"y":',
        '"width":',
        '"height":',
        "persistent-id",
        "fromSide",
        "toSide",
        "secret-background",
        '"plugin"',
    ):
        assert hidden not in dumped
    assert path.read_bytes() == raw and list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize(
    "start,end,direction",
    [
        ("none", "arrow", "forward"),
        ("arrow", "none", "reverse"),
        ("arrow", "arrow", "both"),
        ("none", "none", "none"),
    ],
)
def test_arrow_directions(saved, start, end, direction):
    path, doc = saved
    doc["edges"][0].update(fromEnd=start, toEnd=end)
    path.write_text(json.dumps(doc))
    assert canvas.run(str(path))["connections"][0]["direction"] == direction


def test_paging_and_selected_card(saved):
    path, _ = saved
    first = canvas.run(str(path), limit=2)
    second = canvas.run(str(path), offset=first["next_offset"], limit=2)
    assert [n["id"] for n in first["cards"] + second["cards"]] == ["n1", "n2", "n3", "n4"]
    assert second["next_offset"] is None
    one = canvas.run(str(path), card="n3", revision=first["revision"])
    assert len(one["cards"]) == 1 and len(one["connections"]) == 1
    assert canvas.run(str(path), card="n4")["connections"] == []


def test_edit_preserves_geometry_extensions_and_exact_backup(saved):
    path, original = saved
    raw = path.read_bytes()
    path.chmod(0o640)
    revision = canvas.run(str(path))["revision"]
    out = canvas.run(
        str(path),
        "edit",
        revision=revision,
        changes=[
            {"op": "update_card", "id": "n2", "set": {"text": "Шинэ", "color": "cyan"}},
            {"op": "update_connection", "id": "e1", "set": {"direction": "reverse"}},
        ],
    )
    after = json.loads(path.read_text())
    expected = copy.deepcopy(original)
    expected["nodes"][1].update(text="Шинэ", color="5")
    expected["edges"][0].update(fromEnd="arrow", toEnd="none")
    assert after == expected
    assert out["changed"] and out["revision"] != revision
    assert path.with_name(out["backup"].split("/")[-1]).read_bytes() == raw
    assert path.stat().st_mode & 0o777 == 0o640


def test_add_connect_remove_and_group_without_coordinates(saved):
    path, _ = saved
    revision = canvas.run(str(path))["revision"]
    canvas.run(
        str(path),
        "edit",
        revision=revision,
        changes=[
            {"op": "add_card", "ref": "new", "text": "New", "group": "n1"},
            {"op": "connect", "from": "n2", "to": "new", "direction": "both", "label": "next"},
            {"op": "remove_card", "id": "n3"},
        ],
    )
    out = canvas.run(str(path))
    new = next(n for n in out["cards"] if n.get("text") == "New")
    assert new["groups"] == ["n1"]
    assert out["connections"][0]["to"] == new["id"]
    assert out["connections"][0]["direction"] == "both"
    assert out["total_connections"] == 1
    canvas.run(
        str(path),
        "edit",
        revision=out["revision"],
        changes=[
            {"op": "remove_connection", "id": "e1"},
        ],
    )
    assert canvas.run(str(path))["connections"] == []


def test_stale_revision_readonly_dryrun_and_invalid_batch_write_nothing(saved, monkeypatch):
    path, _ = saved
    raw = path.read_bytes()
    revision = canvas.run(str(path))["revision"]
    change = {"op": "update_card", "id": "n2", "set": {"text": "Changed"}}
    with pytest.raises(ValueError, match="requires the revision"):
        canvas.run(str(path), "edit", changes=[change])
    with pytest.raises(ValueError, match="changed"):
        canvas.run(str(path), "edit", revision="stale", changes=[change])
    with pytest.raises(ValueError, match="semantic"):
        canvas.run(
            str(path),
            "edit",
            revision=revision,
            changes=[change, {"op": "update_card", "id": "n2", "set": {"x": 9}}],
        )
    monkeypatch.setenv("OMNIMCP_READONLY", "1")
    assert canvas.run(str(path))["cards"]
    with pytest.raises(trust.TrustError, match="READONLY"):
        canvas.run(str(path), "edit", revision=revision, changes=[change])
    monkeypatch.delenv("OMNIMCP_READONLY")
    monkeypatch.setenv("OMNIMCP_DRYRUN", "1")
    assert canvas.run(str(path), "edit", revision=revision, changes=[change])["dry_run"]
    assert path.read_bytes() == raw and list(path.parent.iterdir()) == [path]


def test_concurrent_change_prevents_replace(saved):
    path, doc = saved
    raw = path.read_bytes()
    revision = canvas.run(str(path))["revision"]
    path.write_text(json.dumps({**doc, "newer": True}))
    newer = path.read_bytes()
    with pytest.raises(ValueError, match="changed"):
        canvas._write(path, raw, doc, revision)
    assert path.read_bytes() == newer


def test_readonly_tool_schema_cannot_request_edits(monkeypatch):
    monkeypatch.setenv("OMNIMCP_READONLY", "1")
    try:
        module = importlib.reload(server)
        tools = asyncio.run(module.build_app().list_tools())
        tool = next(t for t in tools if t.name == "canvas")
        assert tool.annotations.readOnlyHint
        assert "changes" not in tool.inputSchema["properties"]
        assert "action" not in tool.inputSchema["properties"]
    finally:
        monkeypatch.delenv("OMNIMCP_READONLY", raising=False)
        importlib.reload(server)


def test_cli_uses_same_one_tool(saved, capsys):
    path, _ = saved
    assert verbs.main(["canvas", str(path), "--card", "n2", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert json.loads(out["result"])["cards"][0]["title"] == "Санаа"


def test_stdio_one_tool_read_edit_roundtrip(saved):
    path, doc = saved

    async def go():
        env = {k: v for k, v in os.environ.items() if not k.startswith("OMNIMCP_")}
        params = StdioServerParameters(command=sys.executable, args=["-m", "omnimcp"], env=env)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert [t.name for t in tools if "canvas" in t.name] == ["canvas"]
            result = await session.call_tool("canvas", {"path": str(path)})
            assert not result.isError, result.content
            assert result.structuredContent is None
            assert len(result.content) == 1
            view = json.loads(result.content[0].text)
            assert view["cards"][1]["text"] == doc["nodes"][1]["text"]
            result = await session.call_tool(
                "canvas",
                {
                    "path": str(path),
                    "action": "edit",
                    "revision": view["revision"],
                    "changes": [{"op": "update_card", "id": "n2", "set": {"text": "Wire OK"}}],
                },
            )
            assert not result.isError, result.content
            result = await session.call_tool("canvas", {"path": str(path), "card": "n2"})
            assert not result.isError, result.content
            assert json.loads(result.content[0].text)["cards"][0]["text"] == "Wire OK"

    asyncio.run(go())
