"""Shared hardening for FastMCP's generated argument validators."""

from functools import wraps

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError


def hide_validation_input(app) -> None:
    """Keep rejected argument values out of FastMCP tool error responses."""
    for tool in app._tool_manager._tools.values():
        model = tool.fn_metadata.arg_model
        model.model_config["hide_input_in_errors"] = True
        model.model_rebuild(force=True)
        original_run = tool.run

        @wraps(original_run)
        async def run(*args, _run=original_run, _name=tool.name, **kwargs):
            try:
                return await _run(*args, **kwargs)
            except ToolError as exc:
                cause = exc.__cause__
                if not isinstance(cause, ValidationError):
                    raise
                details = "; ".join(
                    f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                    for error in cause.errors(include_input=False, include_context=False)
                )
                raise ToolError(f"Invalid parameters for {_name}: {details}") from None

        object.__setattr__(tool, "run", run)
