# Agentic OS MCP

An extensible local Linux MCP server: system measurements, commands and persistent
terminals, files/configs, systemd, packages, network, storage, desktop, browser and
development tools. The existing Hyprland/AT-SPI desktop and Canvas/Kanban tools
remain compatible.

The new **compact profile** exposes seven stable tools backed by a durable user
worker: `discover`, `observe`, `act`, `workflow`, `job`, `events`, `artifact`.
Native capabilities are discovered on demand; long jobs survive MCP disconnection.
Admin actions use graphical polkit authentication. Optional OpenCode delegation uses
the user's existing OpenCode model and credentials.

See [core setup and capability contracts](docs/CORE.md),
[verification and remaining release gates](docs/VALIDATION.md), and
[backend/source provenance](docs/PROVENANCE.md).

```sh
agentic-os-mcp worker install
agentic-os-mcp discover --action system.snapshot
agentic-os-mcp observe system.snapshot
agentic-os-mcp --profile compact  # MCP stdio entry point
```

Legacy remains the default until the paired token/latency and live validation gates
pass. Existing MCP client configuration and CLI verbs are preserved.

## Legacy MCP tools

`desktop`, `screenshot`, `zoom`, `ui`, `marks`, `binds`, `wait_for`, `pointer`,
`keyboard`, `click_ui`, `hypr`, `launch`, `sequence`, and `canvas`. Clipboard access is
optional and disabled by default.

### OpenCode subagent

The `opencode` MCP tool delegates an explicit task to the installed OpenCode CLI:

```json
{"action":"run","prompt":"Explain this project's entry point.","cwd":"/absolute/project"}
```

It returns a `job_id` immediately. Call `{"action":"status","job_id":"j..."}`
for progress and the final `result.answer` and `result.session_id`. Continue with a
new `run` using that `session_id` and the same `cwd`. `model` and `agent` are optional;
defaults come from OpenCode. `auto_approve=true` explicitly enables OpenCode `--auto`.
Permission denials remain in force. The default timeout is 3600 seconds.

Read running raw events with `{"action":"output","ref":"a...","offset":0}`
using `progress.output`; follow `next` for subsequent bytes. Completed jobs also
include `result.answer_artifact` for the full answer. To stop, call
`{"action":"cancel","job_id":"j..."}` and poll status for termination.
Cancellation does not undo completed edits. Replies are data; verify task effects.

Requires authenticated OpenCode and a running user worker (`agentic-os-mcp worker
install`). Each run uses `--standalone`, so cancellation controls its own CLI/server
process group. Jobs survive MCP disconnection while the worker runs. Read-only mode
omits the tool; dry-run does not launch OpenCode. This is a user process, with the
permissions of the signed-in account. Reconnect the MCP client after updating.

Compact profile exposes the same capability through `act(action="opencode.run", ... )`,
with existing `job` and `artifact` tools for results. CLI example:

```sh
agentic-os-mcp discover --action opencode.run
agentic-os-mcp act opencode.run --params '{"prompt":"Explain this project.","cwd":"/absolute/project"}'
agentic-os-mcp job jRETURNED_ID
```

### Markdown Kanban

Set `AGENTIC_OS_KANBAN_FILE` to the absolute path of an existing Obsidian Kanban
`.md` file to enable four additional MCP tools:

| Tool | Purpose |
| --- | --- |
| `kanban_read` | Read column names, task IDs, text, checkboxes and the board revision; filter and paginate. |
| `kanban_add` | Add a card to an existing column using the latest revision. |
| `kanban_update` | Replace text or append result lines, move a card, or change its checkbox. |
| `kanban_wait` | Wait up to 30 seconds for a file revision to change, then reread. |

For example, merge the environment setting into the existing Codex MCP entry:

```toml
[mcp_servers.agentic-os-mcp.env]
AGENTIC_OS_KANBAN_FILE = "/absolute/path/to/kanban.md"
```

Reconnect the MCP client after changing server configuration or installing an
updated package. Kanban calls do not require a desktop snapshot. The server
only accesses the configured board; tool calls cannot supply another file path.
The file must have `kanban-plugin: board` (or `basic`) frontmatter, unique named
`##` columns, and `- [ ]` / `- [x]` cards. Indented multiline cards, UTF-8 and
CRLF are supported. Settings, archived content and unrelated cards are preserved.

Start with `kanban_read`. Pass its `revision` as `expected_revision` to every
write and use the returned revision for the next operation. Existing cards get
stable Obsidian `^kanban-...` block IDs on their first edit; new cards receive
them immediately. Until then, a `legacy-...` ID is tied to that board revision.
Read a single `task_id` for its full text if a paginated preview is truncated.
Moving a card preserves its checkbox unless `checked` is explicitly supplied.

Use `append_text` to add a result without resending the original instructions;
it cannot be combined with `text` (replacement). Append, move and checkbox changes
can be committed together against one revision. For example, after verifying the
task's acceptance conditions:

```json
{"task_id":"kanban-ID","expected_revision":"HASH","column":"Дууссан","checked":true,"append_text":"Үр дүн: YouTube нүүр шинэ tab-д нээгдэв; https://www.youtube.com/ хаягийг шалгав."}
```

Kanban MCP results contain one compact JSON text block, without duplicate
structured content. Write receipts include the task ID, column, checkbox and
new revision; they omit card text. Read the card by `task_id` when text is needed.
The Python `kanban` module still returns dictionaries with full write results.
Start with the MCP read rather than reading the same file through a shell, check
the returned path, and filter with `query` or `column` when the task is known.
Browser tasks still require a connected browser tool; this server manages the
desktop and board and does not provide a browser tab API.

Writers are serialized with an advisory lock and stale revisions are refused.
Writes use a temporary file plus atomic replacement and recheck the original
bytes/stat immediately beforehand. Obsidian does not share the advisory lock:
an external edit in the final check/replace interval is still a possible race.
Finish an interactive edit before asking an agent to write, and reread on a
conflict. Symlink board files, malformed boards and files over 2 MiB are refused.

Read-only mode exposes only `kanban_read` and `kanban_wait`; dry-run validates
mutations and returns a preview without writing. These tools track tasks; they
do not execute card text, start agents, or provide an unattended dispatcher.

Read `desktop` first. Prefer `ui` and `click_ui` for accessible controls. When a
window is hidden, `screenshot(window=...)` captures its own surface when the
compositor supports it, so the user's workspace does not need to switch. A
hidden application may return its last rendered frame. Use visible-window
screenshots when the latest visual state matters.

For Obsidian `.canvas` files, use the single `canvas` tool directly. It returns
titles, full card text, types, colors, group membership, file/URL references,
and connection endpoints, directions, labels and colors. Geometry, background
settings and persistent IDs stay internal; short `n1`/`e1` references identify
cards and connections. Results are compact text, without a duplicate JSON payload.
Read all pages using `next_offset`; `card="n1"` selects one card and its connections.

`action="edit"` accepts semantic changes with the `revision` from a read. It
preserves existing geometry and extension fields, saves a verified hidden sibling
backup, and atomically replaces the file. Save in Obsidian first; unsaved editor
state is unavailable. External editors do not share the MCP write lock: avoid
simultaneous editing. Read again after changes for current short references.
Read-only mode exposes the same tool with only read parameters; dry-run validates
edits without writing. No desktop session is needed for Canvas access.

```sh
agentic-os-mcp canvas /path/Plan.canvas
agentic-os-mcp canvas /path/Plan.canvas --card n2
agentic-os-mcp canvas /path/Plan.canvas --action edit --revision HASH --changes @changes.json
```

## Install

```sh
uv tool install --from /mnt/work/PROJECTS/LINUX/agentic-os-mcp agentic-os-mcp
agentic-os-mcp --version
agentic-os-mcp doctor
```

Register `agentic-os-mcp` as a stdio MCP server. Forward the active session's
`WAYLAND_DISPLAY`, `HYPRLAND_INSTANCE_SIGNATURE`, `XDG_RUNTIME_DIR`, and
`DBUS_SESSION_BUS_ADDRESS` environment variables.

Requirements: Linux, Hyprland, `grim`, `wtype`, and `busctl`. UI tree operations
also need an AT-SPI bus and an application that exposes accessible controls.

## Safety and configuration

The agent and user share the real desktop seat. Authentication prompts are
guarded by default; clipboard access is opt-in. Read-only mode uses
`AGENTIC_OS_READONLY=1`; confinement, background operation, strict focus checks,
dry-run, and journaling are available through `AGENTIC_OS_*` settings. This is
a desktop-control MCP server, not an operating-system sandbox.

MIT license. The original upstream copyright and license terms are retained in
[LICENSE](LICENSE).
