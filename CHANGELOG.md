# Changelog

## Unreleased

- Remove the Canvas and Kanban integrations completely: modules, MCP tools,
  compact actions, CLI commands, board configuration, plugin/skill instructions
  and feature-specific tests. Existing user files and historical audit evidence
  are preserved.

- Use the distinct `OmniMCP-linux` distribution name; preserve the OmniMCP product,
  both command aliases, Python imports and state paths. The PyPI `omnimcp` name
  belongs to a different project; install this project from its explicit Git source.
- Exclude raw VM evidence from source distributions while keeping it in Git.
- Add offline `worker prune`: preview artifact age/size retention, require
  `--apply` for deletion, and refuse active workers or unresolved work.
- Document the audit fixes now integrated into main: single-copy images, typed
  MCP errors and desktop outcomes, honest RPC timeouts, trusted private paths,
  manual root-helper installation and bounded worker/process recovery.
- Standardize the product name as OmniMCP and add the `OmniMCP` command while
  keeping `omnimcp` as a compatible alias.
- Make fake worker socket tests independent of umask; raise the coverage floor
  to 84% and document separate isolated-VM live tests.
## 0.2.0 — OS core

- Add opt-in seven-tool compact profile and compatible CLI operations.
- Add private Unix worker, SQLite jobs/events/artifacts, cancellation/recovery,
  resource locks and deterministic workflows without an internal LLM.
- Add native OS/file/process/service/package/network/storage/audio/device/development
  adapters, Caelestia controls and a lazy Playwright MCP browser gateway.
- Add graphical admin execution with persistent cancellation guard and an optional
  root-owned config helper; preserve backup/revision/readback receipts.
- Keep legacy desktop/Canvas/Kanban behavior and default profile; refuse ambiguous
  desktop sessions. Add real worker/MCP/PTY tests and benchmark release gates.

## 0.1.0

- Initial local OmniMCP package for Hyprland and Wayland.
- Includes desktop observation, accessible UI, screenshots, input, and workspace tools.
