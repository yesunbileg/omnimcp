"""Typed capability contracts, independent of MCP and desktop transports."""

from __future__ import annotations

import importlib.util
import inspect
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_type_hints

from pydantic import ConfigDict, ValidationError, create_model


class Fault(Exception):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code, self.details = code, details

    def result(self) -> dict:
        return {"status": self.code, "message": str(self), **self.details}


@dataclass
class Action:
    name: str
    handler: Callable
    model: Any
    description: str
    readonly: bool = False
    dependencies: tuple[str, ...] = ()
    privilege: str = "user"
    verification: str = "Result includes backend exit status; inspect state after changes."
    undo: str | None = None
    idempotent: bool = False
    resources: Any = ()
    example: dict | None = None
    available: Callable | None = None

    def availability(self) -> dict:
        missing = []
        for dep in self.dependencies:
            found = (
                importlib.util.find_spec(dep[3:]) is not None
                if dep.startswith("py:")
                else shutil.which(dep) is not None
            )
            if not found:
                missing.append(dep)
        if missing:
            return {"status": "missing_dependency", "dependencies": missing}
        return self.available() if self.available else {"status": "available"}

    def validate(self, params: dict) -> dict:
        try:
            return self.model.model_validate(params).model_dump()
        except ValidationError as exc:
            raise Fault("invalid_params", str(exc)) from exc

    def contract(self) -> dict:
        return {
            "action": self.name,
            "description": self.description,
            "readonly": self.readonly,
            "availability": self.availability(),
            "parameters": self.model.model_json_schema(),
            "privilege": self.privilege,
            "dependencies": list(self.dependencies),
            "verification": self.verification,
            "undo": self.undo,
            "idempotent": self.idempotent,
            "example": self.example,
        }


class Registry:
    def __init__(self):
        self.actions: dict[str, Action] = {}

    def add(
        self,
        name: str,
        handler: Callable,
        *,
        params: dict | None = None,
        description: str = "",
        **metadata,
    ) -> Action:
        if name in self.actions:
            raise ValueError(f"duplicate capability: {name}")
        if params is None:
            hints = get_type_hints(handler)
            params = {
                p.name: (
                    hints.get(p.name, Any),
                    ... if p.default is inspect.Parameter.empty else p.default,
                )
                for p in inspect.signature(handler).parameters.values()
                if p.name != "ctx"
            }
        model = create_model(
            name.replace(".", "_"),
            __config__=ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True),
            **params,
        )
        action = Action(
            name, handler, model, description or inspect.getdoc(handler) or name, **metadata
        )
        self.actions[name] = action
        return action

    def get(self, name: str) -> Action:
        if name not in self.actions:
            raise Fault("unsupported", f"Unknown action: {name}; use discover.")
        return self.actions[name]

    def discover(
        self,
        query: str = "",
        action: str = "",
        offset: int = 0,
        limit: int = 30,
        readonly: bool = False,
    ) -> dict:
        if action:
            found = self.get(action)
            if readonly and not found.readonly:
                raise Fault("permission_required", "This worker is read-only.")
            return found.contract()
        words = query.lower().split()
        found = [
            a
            for a in self.actions.values()
            if (not readonly or a.readonly)
            and all(w in f"{a.name} {a.description}".lower() for w in words)
        ]
        return {
            "items": [
                {"action": a.name, "readonly": a.readonly, **a.availability()}
                for a in found[offset : offset + limit]
            ],
            "total": len(found),
            "next": offset + limit if offset + limit < len(found) else None,
        }
