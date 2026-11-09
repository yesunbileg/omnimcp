# Canvas/Kanban feature removal

The user explicitly requested removing both integrations. This change removes
their modules, legacy MCP registrations, compact capabilities, CLI parser and
dispatch handling, board environment forwarding, plugin/skill guidance and
current feature documentation. Feature-specific tests are removed with the
features; new regressions require unknown/unsupported responses, absent imports,
and preservation of existing user files.

The original audit at `eaabe434519a291dd5f8108014fe7186570e5418` remains a historical
record. Its raw evidence and checksums are unchanged. AC01's Canvas writer and
AC05's Kanban append route no longer exist; this is removal, not a claim that
their old implementations were repaired. General journal free-text handling
has not been changed or certified by this removal.

The stop FIFO, JPEG compatibility, named-seat keyboard lifecycle and D-Bus
decoder findings remain outside this change. No fix to those is claimed.
Existing user documents, backups, state and journals are untouched.

## Validation

- Seven removal regressions failed before the change, then passed. They cover
  both legacy discovery modes, real MCP unknown-tool responses, unsupported
  compact actions, absent modules, CLI rejection and preserved user files.
- Focused transport/policy/validation suite: 89 passed.
- Full suite under umask 022 with subprocess coverage: 1,496 passed,
  16 deselected; coverage 84.73%, existing 84% floor retained.
- Ruff check, Ruff format check and diff whitespace check passed.
- Fresh wheel and sdist contain neither removed module; the packaged skill
  matches its source and has no removed-feature instructions. Plugin JSON is valid.
- A fresh installed wheel was exercised through real MCP stdio: legacy has
  15 tools with clipboard disabled, read-only has 8. Removed tool names are
  rejected even with the old board environment configured; its fixture file is unchanged.
- Independent read-only Terra review found no actionable P0–P3 issue in the
  removal. No new live-desktop run or unrelated audit fix is claimed.
