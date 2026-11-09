# OmniMCP Codex plugin

This plugin package (manifest version `0.2.1`) starts an installed OmniMCP
runtime (`0.2.0`) through `bin/OmniMCP`. It does not include or install the
runtime or credentials.

Install OmniMCP first as described in the repository [setup guide](../../../docs/start.md).
The shim uses `OMNIMCP_BIN` when set; otherwise it finds `OmniMCP`
(or the compatible `omnimcp`) on `PATH` and
refuses to run itself recursively. The server needs the active Hyprland session
variables: `WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE`, `XDG_RUNTIME_DIR`,
and `DBUS_SESSION_BUS_ADDRESS`.

Set optional values in this plugin's own `mcp.json` `env` map, for example:

```json
"env": {
  "OMNIMCP_BIN": "/absolute/path/to/OmniMCP"
}
```

Use the same `env` values in `.mcp.json` for Codex compatibility. That manifest
also forwards the four desktop session variables with `env_vars`. Keep the
plugin as the only registration; do not add a duplicate standalone
`mcp_servers.omnimcp` entry. See the [setup guide](../../../docs/start.md) for
manifest setup and session details.

Add this checkout as a local marketplace and install the plugin:

```sh
codex plugin marketplace add /path/to/omnimcp/packaging/codex
codex plugin add omnimcp@omnimcp-local
```

The package contains both portable Agent Plugins manifests and the Codex
compatibility `.mcp.json`; each starts the relative shim and forwards the
desktop session variables. Open a new chat after installation or update.
