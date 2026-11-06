# omnimcp core

The local Arch/Hyprland implementation adds a transport-independent registry,
SQLite state, owner-only Unix socket worker, jobs, events, artifacts, explicit
native adapters and an optional lazy Playwright MCP backend. The optional
`opencode.run` adapter delegates explicit tasks to the installed OpenCode CLI,
using its existing model and credentials. Core OS actions do not require an LLM.

## Profiles and installation

`omnimcp` and all existing desktop/Canvas/Kanban verbs keep their previous
behavior. `--profile legacy` explicitly selects that surface. Compact is opt-in:

```sh
uv sync
uv run omnimcp worker install
uv run omnimcp --profile compact
```

The worker installer writes and enables `~/.config/systemd/user/omnimcp.service`
using the interpreter that ran installation. It does not require sudo. Use the
installed package's CLI when installing the permanent unit; an interpreter in a
removed checkout/virtualenv cannot start it. A user systemd manager must be
available. `worker run` serves in the foreground for isolated development.

Stop all compact work, including child processes: `omnimcp worker stop`.
The old `stop` command controls the legacy desktop beacon. Inspect individual
jobs with `job`; cancellation is cooperative and does not undo completed changes.
User services normally stop at logout; configuring systemd linger is a separate
user choice. Jobs survive MCP/CLI disconnects while the worker remains running.

Set `OMNIMCP_PROFILE=compact` or use `args = ["--profile", "compact"]` in
an MCP client to opt in. The existing client configuration is retained until
all benchmark gates have been measured. Reconnect clients after package updates.

Worker state defaults to `~/.local/state/omnimcp/`; its SQLite database,
artifact files and directory are private. The socket defaults to
`$XDG_RUNTIME_DIR/omnimcp-core/worker.sock`, mode 0600, with a peer UID
check. Override `OMNIMCP_STATE_DIR`/`OMNIMCP_SOCKET` for isolated tests.
Worker environment belongs in a systemd user drop-in. Environment on a later
MCP bridge cannot silently change the worker's desktop session, credentials,
Kanban file, browser profile or backend configuration.

## Compact API

| Tool | Purpose |
| --- | --- |
| `discover` | Search compact capability summaries; `action` retrieves one schema/contract. |
| `observe` | Execute only registry-declared read-only actions; filter/project/paginate rows. |
| `act` | Validate then submit a durable job; `background=false` runs synchronously. |
| `workflow` | Deterministic steps, earlier-result references, conditions, assertions and bounded waits. |
| `job` | Read result/history or request cancellation. |
| `events` | Changes after a durable numeric cursor, including job/action/worker events. |
| `artifact` | Read retained bytes using offsets; binary mode returns base64 for lossless reconstruction. |

Only text content is returned, without a duplicate MCP structured result. The
serialized result budget is 16 KiB. Oversized results return an artifact reference,
preview and `complete=false`; the complete original result is retained. Commands
stream output to artifact files rather than collecting unbounded output in RAM.
`job.progress.output` makes running command output readable. Artifacts currently
remain until explicitly removed from the private state directory; there is no
automatic retention policy or disk quota. State/backups can contain sensitive
application data, so retain the same care as the source files.

`OMNIMCP_READONLY=1` on the worker blocks changes for every client. On a compact
bridge it also filters discovery, removes act/workflow and disallows cancellation.
`OMNIMCP_DRYRUN=1` on the worker validates capabilities but delivers no acting
operation. These policies are not an OS sandbox: a normal acting client has the
signed-in user's authority, including arbitrary user commands and custom adapters.
A CLI/bridge variable cannot reduce or expand the daemon's environment retroactively.

```sh
omnimcp discover --action file.patch
omnimcp observe system.snapshot --fields '["memory","load"]'
omnimcp act command.exec --params '{"argv":["uname","-r"]}'
omnimcp job jCOPY_RETURNED_ID
omnimcp artifact aCOPY_RETURNED_ID --offset 0
```

Action status must be checked. `queued` means accepted, not completed.
`missing_dependency`, `permission_required`, `unsupported`, `stale_reference`,
`stale_revision`, `auth_cancelled`, `auth_timeout`, `verification_failed` and
`interrupted` have distinct meanings. Missing dependencies are reported before
creating an action job. A successful command exit is not a promise about a
higher-level effect; semantic mutations include their verification/readback.
Legacy desktop text is retained with its verification limits. Focus/close
adapters independently check compositor state; low-level input cannot prove an
application's intended effect without a subsequent semantic observation.

## Workflows and jobs

```json
{
  "steps": [
    {"id":"read","action":"file.read","params":{"path":"/tmp/aos-fixture"}},
    {"id":"edit","action":"file.patch","params":{
      "path":"/tmp/aos-fixture","before":"old","after":"new",
      "expected_revision":{"$ref":"read.revision"}},
      "assert":{"path":"verified","equals":true}}
  ],
  "timeout_s":60
}
```

Step IDs are unique identifiers; references point to earlier steps and traverse
object keys/list indices. `when` uses a previous-result `path` and `equals`;
`assert` uses the current action's result. `wait` polls a read-only action until
`path` equals its value, with `timeout_s` and `interval_s`. `retry` is limited to
0..3 and requires an explicitly idempotent capability. Authentication cancellation,
permission refusals and stale data never auto-retry. Maximum 256 steps and 24 hours,
independent of legacy desktop sequence limits. A workflow is not a transaction;
completed changes remain on failure, with undo receipts where supported.

Named deterministic recipes: `recipe.diagnose_slow`, `recipe.diagnose_service`,
`recipe.install_launch`, `recipe.config_reload`, `recipe.backup_verify`.

The worker runs four independent jobs concurrently. Named resources serialize
file/config paths, desktop input/marks, package databases, service units, browser
state, devices and GUI authentication. Arbitrary command jobs can opt into a
shared `resource` name; the server cannot infer every resource touched by arbitrary
programs. Desktop commands issued outside this worker do not share its mutexes.
A worker restart marks queued/running jobs `interrupted` and never replays them.
The systemd unit uses `KillMode=control-group` to terminate daemon-owned children.
After any interruption/cancellation inspect real state before retrying a change.
If elevation makes a child unsignalable by this user, the result explicitly reports
`cancellation_pending`/`timeout_pending`, its PID and retained output, rather than
claiming termination or opening another authentication prompt.
Persistent PTYs survive bridges, have a controlling terminal, and expire when the
worker stops. Process references include process birth time to detect PID reuse.
Compact desktop references use compositor stable IDs, with process-birth fallback
on older Hyprland; that fallback cannot prove same-process window-address reuse.

## Native capabilities and extension contract

Use `discover` for the current catalog and each parameter schema. Included domains:

- System/thermal/disk measurements, process tree/signals, commands and persistent PTY.
- systemd services/timers and journal cursors; start/stop/restart/reload/enable/disable.
- Pacman transactions, Flatpak scope-aware transactions, checksum-verified local
  AppImage installation and XDG desktop entries/launching.
- File search/read/literal patch/write/move/restore and config reload/verification.
- Network interfaces/routes/DNS/ports, existing NetworkManager connection activation
  with a native checkpoint; new credential provisioning stays in the native GUI.
- Storage inventory/mounts and optional restic backup/check/verified restore.
- All existing desktop operations, Canvas and configured Kanban operations.
- Caelestia theme/DND/brightness/notification observation without restarting the shell.
- WirePlumber audio, BlueZ devices, UPower, USB, optional ADB, Git, build/test jobs,
  Docker, SSH BatchMode and optional libvirt VM inventory.
- Optional Playwright browser backend with explicit tab selection and semantic controls.
- Optional `opencode.run` subagent tasks: explicit project directory, model/agent overrides,
  session continuation, retained answers/events, deadlines and cooperative cancellation.
  Runs use a private OpenCode server; same-directory jobs are serialized. See README.

Not every backend has a specialized semantic wrapper. AUR build/privilege orchestration,
advanced routing/firewall edits, disk formatting/partitioning, health tools, VM lifecycle,
Bluetooth agents and application-specific APIs remain accessible through user commands
(`command.admin_exec` uses GUI elevation when required) or separately installed adapters.
Destructive disk/network scenarios require disposable
VM validation. There is no claim of whole-disk/package-upgrade rollback.

A custom installed Python package can export an entry point in
`omnimcp.adapters`, pointing to `register(registry)`. A capability handler
receives `ctx` and typed parameters. `registry.add` records readonly, dependencies,
availability, privilege, resource locks, verification, undo, idempotency and example.
Pydantic rejects unknown fields and incompatible types. `ctx.run` provides retained
output, cancellation and graphical admin dispatch; `ctx.check`/`ctx.sleep` cooperate
with cancellation/deadlines. Do not mark mutating handlers read-only or repeatable
unless their entire behavior satisfies that contract. No adapter may automatically
install dependencies or prompt for passwords through AI input.

## Admin and preservation

Only `pkexec` is used for core admin commands. No password parameter, terminal
password channel or sudo retry is implemented. A cancellation/timeout blocks further
GUI admin prompts in SQLite. Only after asking the human may a caller set
`auth_retry=true`; this grants one new attempt, not a workflow/session bypass.
Installing/enabling the user worker itself needs no elevated privileges.

`admin.install_helper` explicitly installs the standalone `root_helper.py` to
`/usr/local/libexec/omnimcp-file-helper` with root ownership using a GUI prompt.
It is optional and is not installed silently. `config.admin_update` refuses a missing,
user-writable or incorrectly owned helper/ancestor. The helper uses `/usr/bin/python3 -I`
and only standard-library imports, so elevated execution never imports the editable
Python package. Root backups stay under `/var/lib/omnimcp/backups/<uid>/`.
Each use goes through pkexec again, preserving native authentication policy.

User file edits check SHA-256 revisions, produce diffs, retain and verify backups,
preserve mode/ownership/xattrs, replace atomically and verify readback. `preview=true`
returns the proposed diff. Symlink paths are refused; choose the target explicitly.
Advisory locks coordinate cooperating writers; unrelated programs do not honor them.
NTFS3 and ext4 differ in permission semantics and must be tested separately. A file
restore does not automatically reload an application. `config.update` requires
explicit reload and verification commands and reports failure separately with undo.
Network connection changes create a native timed checkpoint before activation and
commit only after active UUID readback; failure/disconnect lets the checkpoint roll
back. This is not an internet-connectivity or VPN-reachability guarantee.

## Browser and screenshots

Run `scripts/install-browser.sh` explicitly to install pinned `@playwright/mcp@0.0.83`
and its Chromium under the current user, writing private
`~/.config/omnimcp/browser.json`. No root package installation is involved.
Alternatively set `OMNIMCP_BROWSER_COMMAND` to a JSON argv list. The backend
starts on the first browser action, not on worker startup. Default installation
uses headless Chromium and a separate persistent automation profile. Connecting
a user's browser/CDP session requires explicit configuration. Browser data/DOM
is untrusted; authentication/secret fields belong to the human.

List automation tabs, explicitly select one with `browser.tab`, then observe
`browser.snapshot`. Navigation/click/fill require the explicit tab index. A stale
control reference is rejected by Playwright; re-observe instead of guessing.
Screenshot capture uses the existing direct window/crop implementation and never
switches tabs/workspaces to obtain a shot. Hidden windows unsupported by the
capture backend are refused. Any higher-level workflow that intentionally switches
views is responsible for restoring the user's view promptly.

## Verification and benchmark gate

Run `uv run pytest` and the focused lint command documented in `VALIDATION.md`.
The installed host smoke record includes ext4/NTFS3 preservation, service restart,
desktop/screenshot and real browser form interactions.
The new suite includes real worker processes and MCP round trips without modifying
ambient system services/packages/devices. Live host smoke checks are recorded
separately; mocked GUI auth is not equivalent to testing the real polkit agent.

`uv run python scripts/benchmark.py` measures tool schema bytes and warmed engine
dispatch overhead. It does not estimate tokens or include Unix socket/MCP startup.
`docs/benchmark-tasks.json` defines the 20 representative paired tasks.
`--traces <JSONL>` evaluates actual tool-related token and round-trip counts from
the same model/client/initial states, including discovery, images and retries.
The compact default must wait for >=50% median token/round-trip reduction, no
success-rate regression and live correctness/overhead gates. Local byte savings
alone do not satisfy that gate. No additional LLM/API is needed by the MCP server;
the model/client comparison is an external release validation activity.
