"""Strict validation for the local socket as well as the MCP-facing boundary."""

from typing import Any

from pydantic import ConfigDict, ValidationError, create_model

from .registry import Fault

COMMON = {"readonly": (bool, False)}
SPECS = {
    "discover": {"query": (str, ""), "action": (str, ""), "offset": (int, 0), "limit": (int, 30)},
    "observe": {
        "action": (str, ...),
        "params": (dict[str, Any], {}),
        "fields": (list[str], []),
        "filter": (dict[str, Any], {}),
        "offset": (int, 0),
        "limit": (int, 30),
    },
    "act": {
        "action": (str, ...),
        "params": (dict[str, Any], {}),
        "background": (bool, True),
        "auth_retry": (bool, False),
    },
    "workflow": {"steps": (list[dict[str, Any]], ...), "timeout_s": (float, 3600)},
    "job": {"job_id": (str, ""), "cancel": (bool, False), "offset": (int, 0), "limit": (int, 30)},
    "events": {"since": (int, 0), "limit": (int, 50), "kind": (str, "")},
    "artifact": {
        "ref": (str, ...),
        "offset": (int, 0),
        "length": (int, 8192),
        "binary": (bool, False),
    },
}
MODELS = {
    op: create_model(
        "rpc_" + op,
        __config__=ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True),
        **COMMON, **spec
    )
    for op, spec in SPECS.items()
}


def validate(request):
    if not isinstance(request, dict) or request.get("op") not in MODELS:
        raise Fault("unsupported", "Unknown RPC operation.")
    op = request["op"]
    try:
        return {
            "op": op,
            **MODELS[op]
            .model_validate({k: v for k, v in request.items() if k != "op"})
            .model_dump(),
        }
    except ValidationError as exc:
        raise Fault("invalid_params", str(exc)) from exc
