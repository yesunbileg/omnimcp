# 0.2.0 — OS core

- Add opt-in seven-tool compact profile and compatible CLI operations.
- Add private Unix worker, SQLite jobs/events/artifacts, cancellation/recovery,
  resource locks and deterministic workflows without an internal LLM.
- Add native OS/file/process/service/package/network/storage/audio/device/development
  adapters, Caelestia controls and a lazy Playwright MCP browser gateway.
- Add graphical admin execution with persistent cancellation guard and an optional
  root-owned config helper; preserve backup/revision/readback receipts.
- Keep legacy desktop/Canvas/Kanban behavior and default profile; refuse ambiguous
  desktop sessions. Add real worker/MCP/PTY tests and benchmark release gates.

# Changelog

## Unreleased

- Standardize the product name as OmniMCP in the CLI, MCP server, plugins and
  documentation. Add the `OmniMCP` command; keep `omnimcp` as a compatible alias.
- Reduce shared MCP instructions and serialize Kanban results once as compact
  JSON. Return small write receipts and support revision-checked `append_text`
  so recording a result does not require resending the task's instructions.
- Add one `canvas` tool and CLI verb for semantic Obsidian Canvas read/edit:
  full content, colors, grouping and directed connections without geometry or
  persistent IDs. Include revision checks, verified backups, atomic writes,
  read-only support and dry-run validation.

## 0.1.0

- Initial local OmniMCP package for Hyprland and Wayland.
- Includes desktop observation, accessible UI, screenshots, input, and workspace tools.
