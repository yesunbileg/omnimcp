# Agentic OS for Codex

A local plugin wrapping the installed Agentic OS MCP server (0.2.0) and the
existing desktop workflow skill. The server runtime is not copied or reinstalled.

## Requirements

This personal package uses `/home/home/.local/bin/agentic-os-mcp` through the
plugin-contained `bin/agentic-os-mcp` shim, plus the existing Hyprland/Wayland
session. The current Kanban file setting is preserved. No credentials are
packaged. It is intended for this Linux desktop.

The portable Agent Plugins format only permits a bare executable name or a
plugin-relative `./` command, which is why the shim exists. Session variables
(`WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE`, `XDG_RUNTIME_DIR`) are
recovered by the server from the runtime directory; the Codex compatibility
manifest `.mcp.json` still forwards them explicitly for older clients.

## Install or refresh

```sh
codex plugin marketplace add /mnt/work/PROJECTS/LINUX/agentic-os-mcp/packaging/codex
codex plugin add agentic-os-mcp@agentic-os-local
```

The standalone `mcp_servers.agentic-os-mcp` entry in Codex config has been
removed, so the plugin is the only source of these tools. Start a new chat to
load the plugin. Use `desktop` for a harmless live check; do not take a
screenshot for installation.

The package has portable `plugin.json` and `mcp.json`, plus a Codex compatibility
manifest and `.mcp.json` with explicit session environment forwarding. It keeps
the existing server profile; no compact-profile migration or worker changes are
part of this plugin installation.
