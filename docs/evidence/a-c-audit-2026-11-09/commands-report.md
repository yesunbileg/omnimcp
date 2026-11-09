# Command and FFI surface audit

Target: `/workspace/omnimcp`, HEAD `eaabe434519a291dd5f8108014fe7186570e5418` (2026-11-09). Scope: `hyprctl.py`, `input.py`, `keymap.py`, `clipboard.py`, `adapters/apps.py`, plus the Wayland wire layer used by input. Read-only source audit; no checkout, tests, or Git metadata changed.

## Findings

### C1 — P2: virtual keyboard objects accumulate for each named-seat text operation (confirmed)

Source: [`wire.py`](/workspace/omnimcp/src/omnimcp/wire.py:356), [`input.py`](/workspace/omnimcp/src/omnimcp/input.py:166).

Invariant: a long-lived worker should release temporary Wayland protocol objects after the input operation that created them. `input._vk` keeps one `VirtualKeyboard` connection for reuse, while every nonempty `VirtualKeyboard.type_text()` call invokes `_new_keyboard()` and creates a new `zwp_virtual_keyboard_v1` object. It uploads a keymap and sends key events, but never sends the keyboard object's protocol destroy request. The parent connection remains open, so compositor-side virtual keyboard resources accumulate until worker exit. A realistic trigger is repeated `keyboard(type=...)` calls with `OMNIMCP_SEAT` set to a supported named seat and no usable accessibility text field; this routes to the wire keyboard. The cost grows once per call, independent of the number of characters.

Isolated repro: an in-memory fake Wayland client called `type_text('a')` and `type_text('b')`; it recorded two distinct keyboard IDs and the associated key events. `wire.py` has no virtual-keyboard destroy opcode/request, and the protocol object is not otherwise retired. No real compositor or seat was contacted.

Root cause: keyboard creation occurs inside each text call, but cleanup is absent. Minimal fix: add a virtual-keyboard destroy request and send it in a `finally` after each operation (or retain and safely reuse a keyboard object with per-operation keymap handling). Confirmed at the wire-request/source level; accumulated real compositor device count was not observed.

### C2 — P2: failed Wayland client initialization leaks its connected socket (confirmed)

Source: [`wire.py`](/workspace/omnimcp/src/omnimcp/wire.py:126).

Invariant: if initialization fails after opening a socket, the socket must close before the exception escapes. `VirtualPointer.__init__()` only closes around `_resolve_seat()`; failures in the initial registry roundtrip or missing virtual-pointer manager occur before that cleanup block. A fake socket that connected successfully and then returned an empty registry produced `WireError("compositor does not advertise zwlr_virtual_pointer_manager_v1")` while the socket remained open. `_with_pointer()` retries `WireError` once and does not retain the failed instance, so both sockets can leak on a single failed attempt. Repeated tool attempts against a compositor that lacks the protocol, or during failed protocol initialization, can consume worker file descriptors.

Root cause: the connection is acquired before several raising setup steps, with no encompassing cleanup guard. Minimal fix: wrap all post-connect initialization in `try/except BaseException`, close the socket, then re-raise (or make construction use a cleanup-safe context).

## Checks and repros

- Read-only source review of the scoped modules, callers, existing tests, audit follow-up notes, and prior 2026-11-07/08 validation docs.
- `.venv/bin/python -m pytest -q tests/test_hyprctl.py tests/test_input.py tests/test_keymap.py tests/test_clipboard.py` — **85 passed**.
- In-memory Python fixture invoked `VirtualKeyboard.type_text()` twice and counted object IDs/Wayland request opcodes; **2 objects created, no destroy request**.
- In-memory Python fixture monkeypatched socket creation and the initial sync to return no globals; constructor raised and the fake socket's `closed` flag remained **False**.
- No fuzzing or mutation command was run. No full suite was run. No live desktop, clipboard, physical keyboard, or compositor input was used.

## Historical regression status and rejected leads

The 2026-11-07 audit's accepted pointer-rounding issue is documented as fixed for the default seat; the current input path normalizes coordinates before confinement and the focused tests pass. Its stated named-seat positioning/quantization limits remain unverified, not findings here. Prior 2026-11-07/08 audit validation records no finding in this specific keyboard-object cleanup or constructor-failure cleanup path, and they do not claim exhaustive multi-seat testing.

Lua quoting and dispatch construction were reviewed against tests for quote, slash, controls, UTF-8 bytes, attempted Lua code, and argv shape; no concrete injection or quoting defect found. Dispatcher retry only occurs after a successful provider change probe, avoiding blind duplicate dispatch after timeout. Clipboard subprocess calls use argument arrays and timeouts; write avoids captured inherited pipes, and opt-in registration is documented. App launch validates desktop IDs before constructing its command; Flatpak refs/remotes reject option-leading strings and are passed as argv entries. No concrete bug found in these reviewed paths. Arbitrary command execution remains an intentional capability under the calling user's authority and is not treated as a sandbox boundary.
