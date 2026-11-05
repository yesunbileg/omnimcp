# Architecture

Agentic OS MCP is a Python MCP server for the local Linux desktop. The MCP
server, CLI verbs, and Python modules call the same validated tool functions.

## Main modules

- `server.py` registers MCP tools and validates requests.
- `canvas.py` supplies one semantic read/edit tool for saved JSON Canvas files:
  compact references, content and connections, internal geometry, revision checks,
  verified backups and atomic writes. It requires no desktop access.
- `hyprctl.py` reads and changes Hyprland state, including Lua-managed setups.
- `a11y.py` and `dbuswire.py` read and operate accessible UI controls over AT-SPI.
- `screenshot.py` captures monitors, windows, and regions and reports coordinate
  scale metadata.
- `input.py`, `wire.py`, and `keymap.py` provide pointer and keyboard input.
- `background.py` and `trust.py` enforce workspace, focus, authentication, and
  input policies.
- `events.py` waits for compositor events; `server.py` runs bounded sequences.
- `journal.py`, `cli_state.py`, and `safety.py` support optional audit logs,
  one-shot CLI state, dry runs, and emergency stop.

## Tool flow

Use `desktop` to find a window and workspace. Read controls with `ui` or
`marks`; use `click_ui` when a named control exists. For apps without a useful
accessibility tree, capture a screenshot and use `zoom` for small details.
Hidden windows are captured directly when Hyprland and grim support window
capture, avoiding a workspace switch. A suspended app may show its last frame.

All screen coordinates are Hyprland global logical pixels. Screenshot metadata
includes the image origin and scale so image points can be mapped back before
input. Prefer semantic UI actions where possible.

## Safety boundaries

- Calls are checked before dispatch; dry-run mode blocks input and compositor
  changes after validation.
- Authentication prompts and password fields are guarded by default.
- Background mode uses the app accessibility interface and does not move the
  user's cursor. Pointer actions use the real shared cursor.
- Clipboard access is opt-in. Journaling is off by default and redacts typed
  text unless explicitly configured otherwise.
- Tool policy is not an operating-system sandbox; the process runs with the
  signed-in user's permissions.


## OS core and transports (0.2)

- `core/registry.py`: typed action contracts and dependency/availability discovery.
- `core/engine.py`: shared dispatch, policy, resource locks, durable jobs and workflows.
- `core/state.py`: private SQLite jobs/events/auth state and retained artifact bytes.
- `core/execution.py`: cancellable commands, deadlines and graphical-only admin execution.
- `core/worker.py`, `core/client.py`, `core/protocol.py`: authenticated owner-only Unix RPC.
- `compact.py`: seven stable MCP tools; schemas stay independent of capability count.
- `legacy_transport.py`: existing MCP registration over shared validated desktop functions.
- `core_cli.py`: worker management and the seven corresponding CLI operations.
- `adapters/`: files, processes/PTY, systemd/logs, Linux tools, desktop, browser,
  Caelestia, apps, optional root helper and deterministic recipes.
- `root_helper.py`: separately installed, root-owned, standalone Python helper for
  revision-checked admin config updates; never imports user-writable application code.

MCP stdio clients and CLI use the worker socket; persistent jobs/PTYs belong to the
worker. The legacy transport remains direct for compatibility. New adapters register
through Python entry points without growing the compact MCP tool schema. See
`docs/CORE.md` for protocols, privileges, preservation limits and backend configuration.
