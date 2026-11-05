"""Semantic JSON Canvas access. Geometry and persistent IDs stay on disk."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Any

from agentic_os_mcp import journal, trust

COLORS = {str(i): name for i, name in enumerate(
    ("red", "orange", "yellow", "green", "cyan", "purple"), 1
)}
NODE_FIELDS = {
    "text": {"text", "color"}, "file": {"file", "subpath", "color"},
    "link": {"url", "color"}, "group": {"label", "color"},
}
MAX_BYTES = 32 * 1024 * 1024


def _color(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("color must be a string")
    reverse = {v: k for k, v in COLORS.items()}
    value = reverse.get(value, value)
    if value not in COLORS and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("color must be red/orange/yellow/green/cyan/purple, 1-6 or #RRGGBB")
    return value


def _validate(doc: Any) -> None:
    if not isinstance(doc, dict):
        raise ValueError("Canvas must be an object")
    for key in ("nodes", "edges"):
        if not isinstance(doc.get(key, []), list):
            raise ValueError(f"{key} must be a list")
        seen = set()
        for item in doc.get(key, []):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ValueError(f"every {key} entry needs a string ID")
            if not item["id"] or item["id"] in seen:
                raise ValueError(f"empty or duplicate {key} ID")
            seen.add(item["id"])
            if "color" in item:
                if not isinstance(item["color"], str):
                    raise ValueError("color must be a string")
                _color(item["color"])
    ids = {n["id"] for n in doc.get("nodes", [])}
    for node in doc.get("nodes", []):
        kind = node.get("type")
        if kind not in NODE_FIELDS:
            raise ValueError("unsupported card type")
        for key in ("x", "y", "width", "height"):
            value = node.get(key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or (key in ("width", "height") and value <= 0)):
                raise ValueError("card geometry is invalid")
        required = {"text": "text", "file": "file", "link": "url"}.get(kind)
        if required and not isinstance(node.get(required), str):
            raise ValueError(f"{kind} card needs {required}")
        for key in NODE_FIELDS[kind]:
            if key in node and not isinstance(node[key], str):
                raise ValueError(f"{key} must be a string")
    for edge in doc.get("edges", []):
        if edge.get("fromNode") not in ids or edge.get("toNode") not in ids:
            raise ValueError("connection refers to a missing card")
        for key in ("fromEnd", "toEnd"):
            if key in edge and edge[key] not in ("none", "arrow"):
                raise ValueError("invalid connection arrow")
        for key in ("fromSide", "toSide"):
            if key in edge and edge[key] not in ("top", "right", "bottom", "left"):
                raise ValueError("invalid connection side")
        if "label" in edge and not isinstance(edge["label"], str):
            raise ValueError("connection label must be a string")


def _load(path: str) -> tuple[Path, bytes, dict, str]:
    target = Path(path).expanduser().resolve(strict=True)
    if target.suffix != ".canvas" or not target.is_file():
        raise ValueError("path must name an existing .canvas file")
    with target.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Canvas exceeds 32 MiB")
    doc = json.loads(raw)
    _validate(doc)
    return target, raw, doc, hashlib.sha256(raw).hexdigest()


def _refs(doc: dict) -> tuple[dict, dict]:
    return ({f"n{i}": n for i, n in enumerate(doc.get("nodes", []), 1)},
            {f"e{i}": e for i, e in enumerate(doc.get("edges", []), 1)})


def _direction(edge: dict) -> str:
    start = edge.get("fromEnd", "none") == "arrow"
    end = edge.get("toEnd", "arrow") == "arrow"
    return "both" if start and end else "reverse" if start else "forward" if end else "none"


def _inside(node: dict, group: dict) -> bool:
    return (node is not group and node["x"] >= group["x"] and node["y"] >= group["y"]
            and node["x"] + node["width"] <= group["x"] + group["width"]
            and node["y"] + node["height"] <= group["y"] + group["height"])


def _view(doc: dict, revision: str, card: str, offset: int, limit: int) -> dict:
    nodes, edges = _refs(doc)
    ids = {n["id"]: ref for ref, n in nodes.items()}
    if card and card not in nodes:
        raise ValueError("unknown card reference; read the Canvas again")
    groups = [(ref, n) for ref, n in nodes.items() if n["type"] == "group"]
    selected = [(ref, n) for ref, n in nodes.items() if not card or ref == card]
    connections = [(ref, e) for ref, e in edges.items() if not card or
                   nodes[card]["id"] in (e["fromNode"], e["toNode"])]
    cards = []
    for ref, n in selected[offset:offset + limit]:
        text = n.get("text", n.get("label", n.get("file", n.get("url", ""))))
        title = next((line.strip().lstrip("# ") for line in text.splitlines() if line.strip()), "")
        item = {"id": ref, "type": n["type"], "title": title[:100]}
        for field in ("text", "label", "file", "subpath", "url"):
            if field in n:
                item[field] = n[field]
        if "color" in n:
            item["color"] = COLORS.get(n["color"], n["color"])
        membership = [ref for ref, g in groups if _inside(n, g)]
        if membership:
            item["groups"] = membership
        cards.append(item)
    links = []
    for ref, e in connections[offset:offset + limit]:
        item = {"id": ref, "from": ids[e["fromNode"]], "to": ids[e["toNode"]],
                "direction": _direction(e)}
        if "label" in e:
            item["label"] = e["label"]
        if "color" in e:
            item["color"] = COLORS.get(e["color"], e["color"])
        links.append(item)
    total = max(len(selected), len(connections))
    return {"revision": revision, "cards": cards, "connections": links,
            "total_cards": len(selected), "total_connections": len(connections),
            "next_offset": offset + limit if offset + limit < total else None}


def _ends(edge: dict, direction: str) -> None:
    if direction not in ("forward", "reverse", "both", "none"):
        raise ValueError("direction must be forward, reverse, both or none")
    edge["fromEnd"] = "arrow" if direction in ("reverse", "both") else "none"
    edge["toEnd"] = "arrow" if direction in ("forward", "both") else "none"


def _apply(doc: dict, changes: list[dict]) -> None:
    nodes, edges = _refs(doc)
    doc.setdefault("nodes", [])
    doc.setdefault("edges", [])

    def find(table: dict, ref: str) -> dict:
        if not isinstance(ref, str) or ref not in table:
            raise ValueError("unknown reference; read the Canvas again")
        return table[ref]

    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("each change must be an object")
        op = change.get("op")
        allowed = {
            "update_card": {"op", "id", "set"}, "remove_card": {"op", "id"},
            "add_card": {"op", "ref", "text", "color", "group"},
            "connect": {"op", "ref", "from", "to", "label", "color", "direction"},
            "update_connection": {"op", "id", "set"},
            "remove_connection": {"op", "id"},
        }
        if op not in allowed or change.keys() - allowed[op]:
            raise ValueError("unknown operation or field; coordinates are managed internally")
        if op == "add_card":
            ref = change.get("ref")
            if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", ref):
                raise ValueError("add_card needs a short ref for subsequent changes")
            if ref in nodes:
                raise ValueError("card ref already exists")
            text = change.get("text")
            if not isinstance(text, str):
                raise ValueError("add_card needs text")
            group = find(nodes, change["group"]) if "group" in change else None
            if group and group["type"] != "group":
                raise ValueError("group must refer to a group card")
            if group:
                members = [n for n in doc["nodes"] if _inside(n, group)]
                x, y = group["x"] + 30, max(
                    [group["y"] + 50] + [n["y"] + n["height"] + 30 for n in members])
                width = max(320, group["width"] - 60)
                group["width"] = max(group["width"], width + 60)
                group["height"] = max(group["height"], y - group["y"] + 230)
            else:
                x, y, width = 0, max(
                    [0] + [n["y"] + n["height"] + 60 for n in doc["nodes"]]), 320
            node = {"id": uuid.uuid4().hex[:16], "type": "text", "text": text,
                    "x": x, "y": y, "width": width, "height": 200}
            if "color" in change:
                node["color"] = _color(change["color"])
            nodes[ref] = node
            doc["nodes"].append(node)
        elif op in ("update_card", "remove_card"):
            node = find(nodes, change.get("id"))
            if op == "remove_card":
                doc["nodes"].remove(node)
                doc["edges"] = [e for e in doc["edges"] if node["id"] not in
                                (e["fromNode"], e["toNode"])]
                nodes = {k: n for k, n in nodes.items() if n is not node}
                edges = {k: e for k, e in edges.items() if e in doc["edges"]}
            else:
                values = change.get("set")
                if not isinstance(values, dict) or values.keys() - NODE_FIELDS[node["type"]]:
                    raise ValueError("set accepts only semantic fields for the card's type")
                for key, value in values.items():
                    if key == "color" and value is None:
                        node.pop(key, None)
                    else:
                        node[key] = _color(value) if key == "color" else value
        elif op == "connect":
            source = find(nodes, change.get("from"))
            target = find(nodes, change.get("to"))
            ref = change.get("ref", f"new_edge_{len(edges) + 1}")
            if not isinstance(ref, str) or ref in edges:
                raise ValueError("connection ref must be a new string")
            edge = {"id": uuid.uuid4().hex[:16], "fromNode": source["id"],
                    "toNode": target["id"]}
            vertical = abs(target["y"] - source["y"]) > abs(target["x"] - source["x"])
            edge["fromSide"], edge["toSide"] = (
                ("bottom", "top") if target["y"] >= source["y"] else ("top", "bottom")
            ) if vertical else (
                ("right", "left") if target["x"] >= source["x"] else ("left", "right"))
            _ends(edge, change.get("direction", "forward"))
            for key in ("label", "color"):
                if key in change:
                    edge[key] = _color(change[key]) if key == "color" else change[key]
            edges[ref] = edge
            doc["edges"].append(edge)
        else:
            edge = find(edges, change.get("id"))
            if op == "remove_connection":
                doc["edges"].remove(edge)
                edges = {k: e for k, e in edges.items() if e is not edge}
            else:
                values = change.get("set")
                if not isinstance(values, dict) or values.keys() - {"label", "color", "direction"}:
                    raise ValueError("connection set accepts label, color and direction")
                for key, value in values.items():
                    if key == "direction":
                        _ends(edge, value)
                    elif value is None:
                        edge.pop(key, None)
                    else:
                        edge[key] = _color(value) if key == "color" else value
    _validate(doc)


def _write(target: Path, raw: bytes, doc: dict, revision: str) -> tuple[str, str]:
    """Serialize MCP writers, preserve a verified backup, then replace atomically.

    External editors do not share our lock: revision is checked again just
    before replace. The Canvas should be saved in Obsidian before editing.
    """
    data = (json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if len(data) > MAX_BYTES:
        raise ValueError("edited Canvas exceeds 32 MiB")
    lock_dir = Path(tempfile.gettempdir()) / f"agentic-os-canvas-{os.getuid()}"
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    lock_name = hashlib.sha256(os.fsencode(target)).hexdigest()
    with (lock_dir / lock_name).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.read_bytes() != raw:
            raise ValueError("Canvas changed; read again before editing")
        backup = target.with_name(f".{target.name}.{revision}.bak")
        try:
            with backup.open("xb") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(target.stat().st_mode))
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
        if backup.read_bytes() != raw:
            raise ValueError("backup verification failed; original left unchanged")
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                tmp = Path(stream.name)
                os.fchmod(stream.fileno(), stat.S_IMODE(target.stat().st_mode))
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if target.read_bytes() != raw:
                raise ValueError("Canvas changed; read again before editing")
            journal.refuse_if_dry("write Canvas")
            os.replace(tmp, target)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest(), str(backup)


def run(path: str, action: str = "read", card: str = "", offset: int = 0,
        limit: int = 100, revision: str = "", changes: list[dict] | None = None) -> dict:
    if action not in ("read", "edit"):
        raise ValueError("action must be read or edit")
    if (isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
            or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200):
        raise ValueError("offset must be >=0 and limit must be 1-200")
    if action == "edit" and os.environ.get("AGENTIC_OS_READONLY", "").lower() in (
        "1", "true", "yes", "on"
    ):
        raise trust.TrustError("AGENTIC_OS_READONLY is set: Canvas edits are refused")
    target, raw, doc, current = _load(path)
    if revision and revision != current:
        raise ValueError("Canvas changed; read again before using short references")
    if action == "read":
        if changes is not None:
            raise ValueError("changes requires action=edit")
        return _view(doc, current, card, offset, limit)
    if card or offset:
        raise ValueError("card/offset are read options; edits use changes")
    if not revision:
        raise ValueError("editing requires the revision returned by read")
    if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
        raise ValueError("editing needs 1-100 changes")
    edited = copy.deepcopy(doc)
    _apply(edited, changes)
    if edited == doc:
        return {"changed": False, "revision": current}
    if journal.dry_run():
        return {"dry_run": True, "changed": False, "revision": current,
                "validated_changes": len(changes)}
    current, backup = _write(target, raw, edited, current)
    return {"changed": True, "revision": current, "backup": backup,
            "note": "Read again for current short references."}
