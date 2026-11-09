# CLI and lifecycle audit

Audited `/workspace/omnimcp` at `eaabe434519a291dd5f8108014fe7186570e5418` on 2026-11-09. Read `AGENTS.md` and the 2026-11-07 through 2026-11-09 audit/remediation validation documents before reviewing the CLI lifecycle, state, replay, worker retention and process identity paths. Source, tests and Git were not modified. All signal calls in tested CLI code were mocked by existing tests; new repros used only isolated subprocesses and no host desktop or ambient process signals.

## Findings

### P2 — `stop` can block forever on a FIFO in either private coordination path — confirmed

**Location:** [cli.py](/workspace/omnimcp/src/omnimcp/cli.py:247) and [cli.py](/workspace/omnimcp/src/omnimcp/cli.py:209).

**Invariant:** `AGENTS.md` requires private-file reads to reject FIFOs, sockets and devices. The emergency stop must remain usable to reach the process cleanup and beacon signaling path.

**Trigger and proof:** Replaced `cli.lock` with a mode-0600 FIFO under a fresh, mode-0700 isolated runtime directory, then ran `cli.stop()` in a subprocess with a one-second deadline: it remained blocked. Repeated with `state.json` as a FIFO; it also remained blocked. The subprocess deadline terminated only these isolated test processes. `_running_verb_pid()` calls built-in `open()` before it even examines the beacon; later, the beacon branch checks ownership, write bits and symlink status but calls `Path.read_text()` without checking for a regular file. Opening a FIFO for reading blocks before parsing or signaling.

**Root cause and minimal fix:** These two reads bypass `private_paths.open_private_file()`, which already uses no-follow/nonblocking opens and validates regular-file type, owner and mode. Use that helper for both paths and read through the returned descriptor; treat an invalid file as unreadable and continue or refuse promptly.

### P2 candidate — acting-verb stop trusts a bare PID — not confirmed as a wrong-target signal

**Location:** [cli.py](/workspace/omnimcp/src/omnimcp/cli.py:187) and [cli.py](/workspace/omnimcp/src/omnimcp/cli.py:238).

**Invariant:** `AGENTS.md` requires process PID plus start-time identity checks and forbids signaling by name.

**Trigger and proof:** If `cli.lock` is locked, the code parses its contents as a PID and sends SIGTERM directly. The beacon branch just below it verifies psutil `create_time`, but the lock-derived PID branch does not. The existing `test_stop_reaches_a_verb_acting_beside_a_server` confirms this branch sends a mocked SIGTERM to the number stored in the lock. I did not reproduce PID reuse or another realistic benign lifecycle that makes that number refer to a different process while the lock remains held. A stale unlocked lock is harmless because `_running_verb_pid()` first acquires and releases the lock and returns `None`; the runtime directory is also owner-private. Therefore this remains a candidate, not a confirmed wrong-target defect.

**Minimal fix if confirmed:** Persist a process start time alongside the lock PID and verify both immediately before signaling, with a compatibility path that refuses to signal legacy PID-only lock contents.

## Reviewed paths and rejected hypotheses

- Emergency-stop cleanup registration in acting verbs is after successful lock acquisition and uses `safety.on_shutdown(hinput.release_held)`; shutdown drains callbacks before removing its own beacon. The CLI verb path arms cleanup when a live server owns the beacon.
- Beacon stop validates owner, group/world write bits and symlink status, then requires `create_time` equality before SIGTERM. Stale beacons are cleared only after `ProcessLookupError`/`NoSuchProcess`; malformed beacon data fails closed. `_take_beacon()` uses PID liveness only to avoid overwriting a live server beacon; it does not signal that PID.
- `cli_state` and the verb lock writers use private-path opens; state merge is locked and keyed to the compositor instance. Persisted owned-window addresses are pruned against live compositor clients before confinement decisions. No stale-state execution bypass reproduced.
- Replay defaults to plan-only. Execution requires `--execute`, then refuses `OMNIMCP_READONLY` and effective `OMNIMCP_DRYRUN`; unsupported tools, unavailable text digests and missing windows block execution unless the documented skip-missing path applies. The replay origin prevents recursive replay. No journal replay gate bypass reproduced.
- Acting verbs refuse read-only mode before dispatch, and their `--dry-run` feeds the normal guard layer. Exit codes distinguish usage (2), refusal (3), incomplete/refusal-style outcomes (4) and execution errors (1); no contract mismatch reproduced.
- Worker prune is explicit and offline: it takes a nonblocking worker lock, rejects unresolved process/job records, preserves metadata, and requires the stored exact boolean read-only/dry-run policy before `--apply`. The CLI also checks effective read-only/dry-run flags. No pruning-policy bypass reproduced. As requested, the already documented absence of a hard live-output quota is not reported as a new defect.
- Symlink, ownership and mode protections in private path creation/opening were reviewed. The confirmed FIFO finding is specifically the two `stop` readers bypassing that helper. I found no independent lock ownership or symlink issue that crossed the private runtime-directory trust boundary.

## Focused verification

- `.venv/bin/python -m pytest -p no:cacheprovider --basetemp=... tests/test_private_paths.py tests/test_safety.py tests/test_verbs.py -q`: first run **36 failed, 28 passed** because the sandbox represented `/` as an untrusted filesystem root (`PermissionError: untrusted filesystem root`), affecting private-path setup. This was environment-only, not a source regression. The same command rerun with the approved elevated test environment: **64 passed**.
- `.venv/bin/python -m pytest -p no:cacheprovider --basetemp=... tests/test_cli.py tests/test_artifact_retention.py tests/test_journal.py tests/test_cli_state.py -q`: **100 passed**.
- An initial command referenced nonexistent `tests/test_core_cli.py` and collected no tests; corrected to the actual CLI, retention, journal and state files above.
- Individual FIFO repro reruns: `cli.lock` FIFO — **blocked at 1s**; `state.json` FIFO — **blocked at 1s**. Both reproduced independently in isolated subprocesses.
- The output directory is mode `0700`. No full suite was run.
