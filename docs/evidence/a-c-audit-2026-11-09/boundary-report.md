# A↔C enforcement boundary audit

Target: `/workspace/omnimcp`, HEAD `eaabe434519a291dd5f8108014fe7186570e5418`
Scope: `background.py`, `adapters/desktop.py`, `trust.py`, and caller wiring in `server.py` / `verbs.py`. Read-only audit. No checkout source, tests, or Git state changed. The report directory is mode 0700.

## Result

No new P0–P3 enforcement-boundary finding was confirmed in the inspected scope. The three desktop regressions applicable here from the previous F1–F4 audit have regression coverage at this HEAD; F2 concerns CLI cancellation and is outside this boundary.

### Rechecked previous findings

- F1, foreground keyboard receipt: `server.py` captures `seat_before` before focusing and records `seat_after_focus`; `_keyboard_in_background` receives both and reports the full foreground transition. The prior special-workspace behavior is described in the checked-in Nov. 7 VM validation artifacts. Focus itself remains an intended foreground effect.
- F3, concurrent same-class launch association: `launch` now accepts a window only when both its class and requested workspace match. Off-workspace matches become ambiguous and are not moved or marked owned. Its docstring and `docs/CORE.md` explicitly state workspace/class evidence cannot prove universal launch provenance; title is not treated as provenance. This is a documented limit, not a claim of secure compositor identity.
- F4, fractional pointer boundary: `normalize_pointer_point` runs before policy and trust checks; the trust guard sees the rounded coordinates that delivery uses. `tests/test_pointer_quantization.py` includes adjacent allowed/blocked windows and fractional `639.6` input.

No evidence was found that app/window title alone authenticates ownership or bypasses the guards. `OMNIMCP_CONFINE=class:...` is explicitly a class scope and is spoofable by design; `launched` ownership and background workspace restrictions are distinct checks. Launch ambiguity remains documented because compositor class/workspace metadata cannot prove process provenance.

## Side-effect paths and guard-call matrix

The compact adapter maps acting tools to the same `server` functions as legacy MCP registration. Its handler serializes calls with an `RLock`, resolves compact references, then calls the server function. The compact `desktop.focus` and `desktop.close` wrappers call `server.hypr`, so they inherit its policy checks. No adapter-side direct input/compositor dispatch was found.

| Entry point / effects | Before effect | Policy result |
|---|---|---|
| `server.pointer` → move/click/drag wire input | owner `allow_auth` gate; strict seat check; pointer normalization; background policy; argument/button checks; session-lock check for click/drag; confinement/auth via `guard_pointer`; layer note | DRYRUN runs applicable checks and returns before input. Move does not target a window, but under background guarantee pointer is refused because it moves the real cursor. Click and both drag endpoints are guarded. |
| `server.keyboard` foreground path → focus dispatch, type/key wire input | owner override; strict seat; argument/combo/address validation; target resolution and background decision; lock/layer checks; active confinement/auth checks; strict password-role check for `type` | Guards run before focus dispatch. DRYRUN returns before focus or key delivery. Foreground seat receipt covers pre-focus, post-focus and delivery state. |
| `server.keyboard` background path → a11y or Hyprland sendshortcut | Same owner/seat/argument gates, then `_keyboard_in_background` checks target confinement, auth, session lock, active/focused field policy, and seat/capability constraints before delivery | No focus takeover. XWayland limitations are refused/reported. Strict password-tree probe intentionally fails open on unreadable a11y tree, while positive password detection blocks; ordinary auth classes remain separately guarded. |
| `server.click_ui` → accessibility action or focus + pointer click | Owner override; strict seat; exact name/mark validation and freshness checks; background decision; target confinement/auth/session lock; covering layer and click point checks | Background path runs target guards before a11y action. Foreground path runs guards before focus, re-resolves geometry after focus, refuses stale geometry, repeats layer/click-point checks, then clicks. DRYRUN returns before focus. |
| `server.hypr` → workspace/focus/move/close/fullscreen/floating | argument grammar checks; background guarantee refuses view-taking actions and validates hidden agent workspace movement; target confinement or active-window + seat guard | DRYRUN returns before dispatch. The view-changing workspace action is intentionally exempt from window confinement; named window actions are guarded. Address-targeted actions skip strict seat guard by design. |
| `server.launch` → compositor `exec`, optional silent move, ownership mark | launch allowlist check; workspace validation; background policy/agent workspace and visible-workspace checks; confinement scope constrains placement | DRYRUN returns before exec. New window is claimed only after class+workspace association; ambiguous window is neither moved nor marked. A matching window created concurrently on the same workspace remains an acknowledged provenance limit. |
| `server.sequence` | preflights all `allow_auth` overrides; validates top-level shape; dispatches each op through the same server functions, carrying background selection to placement-sensitive operations | Each effect gets its individual guards; `background=true` rejects `hypr` steps that take the human's view. It is a sequential workflow, so earlier successful steps are not rolled back if a later step is refused. |
| clipboard write | `verbs.run` READONLY check and clipboard opt-in; server action validation; dry-run check | Read is also opt-in. Write is effect-free under DRYRUN. CLI does not let tool args override owner environment. |
| compact `desktop.focus` / `desktop.close` | resolves observed reference, then invokes `server.hypr` | Same guard/DRYRUN path as legacy. Compact binding metadata marks these as acting (not readonly). |

Legacy CLI invokes the same module-level server functions. `OMNIMCP_READONLY` refuses acting verbs before invocation; `clipboard` requires `OMNIMCP_CLIPBOARD=1`; `--dry-run` only sets `OMNIMCP_DRYRUN=1`, so caller flags can request stricter behavior but do not clear owner state. `--foreground` cannot override `OMNIMCP_BACKGROUND=1`; `background.decide` refuses it. `allow_auth=true` is rejected unless owner `OMNIMCP_ALLOW_AUTH_OVERRIDE` is enabled, and that check precedes malformed-action validation. In sequence, overrides are preflighted before any step runs. Strict seat state is restored across CLI processes and checked at acting entrypoints.

Read-only coverage includes `desktop`, screenshot/UI/zoom/marks/binds/wait and Canvas read surfaces. They do not dispatch input. `canvas.edit` is marked acting and has its own readonly gating. Invalid tool arguments may still touch the activity beacon before rejection; this writes only OmniMCP runtime bookkeeping and does not deliver desktop input or compositor commands.

## Fail-open and transition review

- `_guarded_active_client` propagates query failures while keyboard window guards are active; it does not swallow a compositor read error and then send keys unchecked.
- `guard_pointer`, `guard_covering_layer`, and strict seat checks fail closed when their required state cannot be resolved. `guard_password_field` is an explicitly documented best-effort positive detector in strict auth mode; unreadable a11y does not disable the independent auth-class check.
- Session-lock recognition treats Hyprland's positive `locked` answer as authoritative. If that query is unavailable, it falls back to a best-effort process scan for known lockers; if both signals are unavailable, input may proceed. The code and tests document that limitation; no contrary guarantee was found in the inspected contract.
- Foreground focus changes happen only after validation/trust checks; click control focus is followed by re-resolution and geometry/layer/pointer rechecks. Keyboard validates action/combo before focus. Dry-run exits before visible focus or delivery.
- Sequence does not provide transaction rollback. Each step is checked before its own side effect; already completed prior steps may remain after a later refusal, as expected for a sequential action tool.
- `OMNIMCP_STRICT` is a contention detector, not a confinement boundary. It detects state changes since OmniMCP's remembered baseline; it cannot identify which actor moved the seat.

## Tests, mutation probe, and limits

Focused tests run: `tests/test_background.py`, `test_background_tools.py`, `test_trust.py`, `test_pointer_quantization.py`, `test_launch.py`, `test_readonly.py`, `test_dryrun.py`, `test_auth_override_policy.py`, `test_verbs.py`, and `test_sequence.py` using `.venv/bin/pytest`. First sandboxed run: 491 passed, 24 failed before CLI behavior because `private_paths._open_parent` rejected sandbox `/tmp` as an “untrusted filesystem root.” Per environment guidance, reran `tests/test_verbs.py` with `require_escalated`: 47 passed. The earlier 24 failures were all in that file; accounting for overlap, the focused set passed completely. No live desktop test was run.

Hand-selected in-memory mutation: removed `trust.guard_allow_auth_override` behavior by replacing it temporarily with a no-op. Baseline `server.pointer(action='bad', allow_auth=True)` raised `TrustError` from the owner gate before action validation; under the mutation it raised `ValueError` for the malformed action. This demonstrates the owner gate protects the public caller path. Mutation was process-local and did not change files. This was one targeted mutation, not comprehensive mutation coverage.

Rejected hypotheses: F1, F3, and F4 as regressions at this HEAD are contradicted by current code and focused tests; class-scope spoofability is inherent to the configured `class:` policy and is not a launch-ownership proof; session-lock fallback is explicitly best-effort when compositor IPC is unavailable; failing password-tree inspection is documented best-effort under strict auth mode. No arbitrary user command execution was assessed as a sandbox defect. Audit was source/caller/test focused, not exhaustive across all compositor versions, accessibility stacks, or app behaviors.
