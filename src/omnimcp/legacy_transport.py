"""Legacy MCP registration; validated desktop functions remain shared with the core."""

from typing import Any


def build_app(desktop) -> Any:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    from omnimcp.core.fastmcp import hide_validation_input

    readonly = desktop.READONLY
    instructions = desktop._instructions
    if not readonly:
        instructions += (
            "\nUse opencode to delegate an explicit subagent task in a project directory. "
            "No desktop snapshot is needed. Poll its job_id for completion and verify effects.\n"
        )
    if desktop.kb.configured():
        instructions += (
            desktop.KANBAN_READONLY_INSTRUCTIONS if readonly else desktop.KANBAN_INSTRUCTIONS
        )
    app = FastMCP("omnimcp", instructions=instructions)
    app._mcp_server.version = desktop.__version__
    from omnimcp.codex_usage import codex_usage

    app.tool(
        structured_output=False,
        annotations=ToolAnnotations(
            title="Codex account usage",
            readOnlyHint=True,
            destructiveHint=False,
            openWorldHint=True,
        ),
    )(codex_usage)
    for tool in desktop._OBSERVE_TOOLS:
        app.tool(
            structured_output=tool.__name__ not in {"screenshot", "zoom"},
            annotations=ToolAnnotations(
                title=desktop._TITLES[tool.__name__], readOnlyHint=True, openWorldHint=False
            ),
        )(tool)
    app.tool(
        name="canvas",
        structured_output=False,
        annotations=ToolAnnotations(
            title="Canvas cards and connections",
            readOnlyHint=readonly,
            destructiveHint=not readonly,
            openWorldHint=False,
        ),
    )(desktop._canvas_readonly if readonly else desktop.canvas)
    if not readonly:
        from omnimcp.opencode import opencode

        app.tool(
            structured_output=False,
            annotations=ToolAnnotations(
                title="OpenCode subagent",
                readOnlyHint=False,
                destructiveHint=True,
                openWorldHint=True,
            ),
        )(opencode)
        acting = [
            desktop.pointer,
            desktop.keyboard,
            desktop.click_ui,
            desktop.hypr,
            desktop.launch,
            desktop.sequence,
        ]
        if desktop.CLIPBOARD:
            acting.append(desktop.clipboard)
        for tool in acting:
            app.tool(
                annotations=ToolAnnotations(
                    title=desktop._TITLES[tool.__name__], readOnlyHint=False, destructiveHint=True
                )
            )(tool)
    if desktop.kb.configured():
        for tool in (desktop.kanban_read, desktop.kanban_wait):
            app.tool(
                structured_output=False,
                annotations=ToolAnnotations(
                    title=desktop._TITLES[tool.__name__], readOnlyHint=True, openWorldHint=False
                ),
            )(tool)
        if not readonly:
            for tool in (desktop.kanban_add, desktop.kanban_update):
                app.tool(
                    structured_output=False,
                    annotations=ToolAnnotations(
                        title=desktop._TITLES[tool.__name__],
                        readOnlyHint=False,
                        destructiveHint=True,
                        openWorldHint=False,
                    ),
                )(tool)
    hide_validation_input(app)
    return app
