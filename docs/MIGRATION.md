# Migrating from Agentic OS MCP

1. Disconnect the MCP client and stop its old stdio server. If the old user
   worker was installed, run `agentic-os-mcp worker stop` and disable its
   automatic restart with `systemctl --user disable agentic-os-mcp.service`.
   Stop any worker started manually as well.
2. Retain the old package or wheel for rollback. Uninstall the old distribution
   using the same package manager used to install it (for example,
   `uv tool uninstall agentic-os-mcp`), then install the tested new wheel (for
   example, `uv tool install /absolute/path/to/omnimcp-0.2.0-py3-none-any.whl`).
3. Change the MCP client command `agentic-os-mcp` to `omnimcp`, or
   `python -m agentic_os_mcp` to `python -m omnimcp`. Rename the server key
   `agentic-os-mcp` to `omnimcp` in the client configuration. Clients that
   qualify tool names by server key must update that prefix too; for example,
   `mcp__agentic-os-mcp__desktop` becomes `mcp__omnimcp__desktop` in clients
   using that convention. Reconnect the client. Install the new user worker
   with `omnimcp worker install` if using the compact profile.
4. Rename environment variables from `AGENTIC_OS_` to `OMNIMCP_`, keeping the
   suffix unchanged (for example, `AGENTIC_OS_READONLY` becomes
   `OMNIMCP_READONLY`). Old names still work and emit a warning on stderr. If
   both names are present, the new name wins, including when its value is
   empty. Warnings contain variable names, never values. Update any stored
   systemd unit and client configuration as well.

Persistent state is **not automatically migrated**. The old default was
`${XDG_STATE_HOME:-$HOME/.local/state}/agentic-os-mcp`; the new default is
`${XDG_STATE_HOME:-$HOME/.local/state}/omnimcp`. Preserve the old directory
for rollback. The default runtime socket moved from
`$XDG_RUNTIME_DIR/agentic-os-mcp-core/worker.sock` to
`$XDG_RUNTIME_DIR/omnimcp-core/worker.sock`. Restart worker and clients with
matching configuration; `OMNIMCP_SOCKET` overrides the socket path.

For rollback, stop the new server and worker (`omnimcp worker stop` and
`systemctl --user disable omnimcp.service`), reinstall the retained old package,
restore the old MCP client command, server key and environment variables, and
restart the old worker if needed. The preserved old state remains at its old
path.
