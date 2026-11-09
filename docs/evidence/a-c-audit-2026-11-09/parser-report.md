# Parser and wire audit — 2026-11-09

Target: `/workspace/omnimcp`, immutable HEAD `eaabe434519a291dd5f8108014fe7186570e5418`. Scope: `dbuswire.py`, `wire.py`, `events.py`, their tests and callers. Read-only review; no repository edits.

## Findings

### P3 — D-Bus array items can consume bytes outside the declared array (candidate; high confidence in parser behavior, limited impact evidence)

**Location:** `src/omnimcp/dbuswire.py:189-201`, especially lines 195-200.

**Expected invariant:** Each array item must be decoded wholly inside the byte range declared by that array's length. Invalid replies should raise `DBusError`, rather than treating bytes from a following value as part of an array item.

**Trigger and impact:** A D-Bus method reply to an AT-SPI call can contain a malformed array whose element length extends beyond its array length. App-provided AT-SPI replies are decoded by this path. The decoder currently bounds an array only against the full D-Bus message; it can silently accept values assembled across the array/following-value boundary. This is a data-integrity/parser-correctness issue. No privilege or trust-boundary bypass was demonstrated; arbitrary user code remains an intentional capability.

**Minimal evidence:** `array-boundary-repro.py` calls `unmarshal("asi", ...)` with array length 4 and a string element consuming 9 bytes; it returns `[['ABCD'], 777]` rather than rejecting the malformed array. The item reader uses the message-wide `_need()` check, while the array loop compares its cursor to `end` only after decoding an entire item.

**Smallest fix:** Track the current array end as a reader bound while decoding each item; reject any item whose alignment or value crosses that bound. Add a malformed-array regression case.

### P2 — Named-seat text typing retains a new virtual keyboard and manager for each call (candidate; medium confidence)

**Location:** `src/omnimcp/wire.py:356-390`, with the persistent connection held at `src/omnimcp/input.py:147-173`.

**Expected invariant:** Every compositor object created for one text operation should be destroyed after use, or reused under a bounded lifetime. The named-seat virtual keyboard connection is deliberately kept open across calls.

**Trigger and impact:** With `OMNIMCP_SEAT` selecting a named seat, each `type_text()` invokes `_new_keyboard()`, which binds a fresh manager object and creates a fresh keyboard object. Neither object is retained for reuse or sent a destroy request. Repeated ordinary text-input calls therefore leave compositor resources alive until the shared Wayland connection closes, allowing unbounded per-worker resource growth through normal tool use.

**Minimal evidence:** `keyboard-resource-repro.py` invokes `_new_keyboard()` twice against a recording shim. It records distinct keyboard IDs and two manager binds/two creates, with no teardown request. The production `type_text()` calls `_new_keyboard()` each time, and `input._vk` is retained for the process lifetime. No real compositor stress test was run.

**Smallest fix:** Destroy the keyboard and its manager after each text operation, including error paths, or retain and reuse bounded resource objects on the shared connection.

## Checked hypotheses not accepted as findings

- D-Bus total frame allocation: `_message()` rejects declared totals above `_MAX_MESSAGE` (128 MiB), reads in 64 KiB chunks, and call/reply waits use a deadline. No separate frame-allocation issue was demonstrated.
- D-Bus connection cleanup: construction failures close the socket; call timeout, read failure, and socket failure close it; `CallError` deliberately leaves a usable connection. The focused socket tests pass.
- Wayland ancillary FD cleanup: `_upload_keymap()` uses `TemporaryFile` as a context manager, so the passed local fd is closed after upload returns. No local fd leak was found.
- Wayland and Hyprland event parsers accept partial frames/lines by buffering them. Their code has no explicit cap for a single incomplete frame/line. A meaningful attacker-controlled route and supported-host impact were not established: these streams come from the user's compositor/event socket, and waits are bounded by socket timeouts/deadlines. Not reported as a finding.
- `parse_global()` / `parse_error()` trust compositor-supplied string lengths and can raise `struct.error` on malformed short bodies. This requires malformed compositor protocol traffic; no untrusted application route or meaningful impact was established.
- `parse_event()` deliberately preserves unknown events as opaque data and permits short known payloads. Existing tests cover those behaviors; no type confusion or authorization consequence was shown.
- `unmarshal("v", b"\0\0")` raises raw `IndexError`; `unmarshal("v", b"\x01\0\0")` raises raw `KeyError` for invalid variant signatures. A valid D-Bus reply cannot contain an empty or invalid variant signature. These malformed-wire cases reinforce the decoder's incomplete validation but were not split into a separate finding because no stronger external impact than one failed tool call was demonstrated.

## Prior audit and regression status

Reviewed `docs/audits/2026-11-07-review.md`, `docs/audits/2026-11-08-remediation-validation.md`, `docs/audits/2026-11-09-followups-validation.md`, and `docs/AUDIT-2026-10-24.md`. They describe prior transport and desktop fixes but do not record either finding above as fixed or documented limitation. Existing D-Bus tests cover valid round trips, truncation, reply matching, timeout, and a private bus, but do not cover array sub-boundaries or malformed variants. Existing wire tests cover message framing and valid registry/error parsing, but not repeated keyboard-resource teardown.

## Commands and limits

- `XDG_RUNTIME_DIR=/workspace/.omnimcp-runtime/audit-ac-2026-11-09/parser/runtime .venv/bin/python -m pytest -q tests/test_dbuswire.py tests/test_wire.py tests/test_events.py` — **55 passed**. Used the escalation-enabled sandbox because the default sandbox returned `EPERM` for the tests' isolated AF_UNIX socketpairs/private D-Bus daemon. No host desktop or privileged operation was used.
- `XDG_RUNTIME_DIR=/workspace/.omnimcp-runtime/audit-ac-2026-11-09/parser/runtime .venv/bin/python /workspace/.omnimcp-runtime/audit-ac-2026-11-09/parser/array-boundary-repro.py` — reproduced malformed array acceptance.
- `XDG_RUNTIME_DIR=/workspace/.omnimcp-runtime/audit-ac-2026-11-09/parser/runtime .venv/bin/python /workspace/.omnimcp-runtime/audit-ac-2026-11-09/parser/keyboard-resource-repro.py` — recorded repeated resource creation without teardown.
- Both repro scripts and this report are in this audit directory. The dedicated runtime directory is mode 0700.
- No mutation/property fuzz campaign, live compositor reproduction, or full test suite was run. Findings reflect source review and the focused evidence above.
