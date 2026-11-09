# Geometry and accessibility audit

Target: `/workspace/omnimcp` at `eaabe434519a291dd5f8108014fe7186570e5418`.
Read-only source/test audit. `AGENTS.md` was read. No source, test, or Git
changes were made; no ambient desktop or real user capture was used. Evidence
is limited to unit tests, isolated Python fixtures, and source inspection.

## Candidate finding

### P2 candidate — the a11y node budget does not bound high-fanout child replies

Source: [a11y.py](/workspace/omnimcp/src/omnimcp/a11y.py:548), `_Walk.__iter__`
(`stack.extend(reversed(_children(...)))`; `_children` is at line 419).

Invariant: `WALK_BUDGET` is documented as limiting the amount of a11y tree read
to 2,000 objects. It limits objects yielded and per-node property calls, but a
single `GetChildren` response is fully decoded into a Python list and all
children are pushed onto `stack` before the next budget check.

Trigger: an app exposes one accessible node with a very large number of direct
children. This can be an unusually large web/app tree or a broken/malicious
same-session application. No actual application exhibiting this was available.

Minimal isolated reproduction (a fake Bus returns 5,000 children at `/root`;
walk budget is 2):

```text
visited= 2 truncated= True children_materialized= 5000
```

Root cause: the walker bounds DFS iteration, but not the fanout list returned
by `_children`. `dbuswire.py` does reject messages above D-Bus's 128 MiB limit
and bus calls have 10-second timeouts, which cap but do not eliminate the
memory amplification from decoding a large legal reply and retaining its
children on the stack.

Minimal proposed fix: make the traversal account for queued nodes as well as
visited nodes, and avoid retaining a complete sibling list when a budget has
already been reached (or cap/stream the children reply if the protocol path
can support that). Preserve `truncated=True` whenever unread children remain.

Status: candidate, not confirmed as a consequential production defect. The
reproduction verifies the bound mismatch in the walker with a deterministic
fixture; no live app, memory pressure, or service impact was demonstrated.

## Historical findings and rejected hypotheses

- Prior deep-audit F4 (default-seat pointer rounding across a confinement
  boundary) remains fixed in this HEAD. `server.pointer` and `click_ui` call
  `input.normalize_pointer_point` before confinement checks. That function
  rounds default-seat points, while preserving named-seat points. The positive
  639.6→640 and negative -0.4→0 adjacent-window regressions are present in
  `tests/test_pointer_quantization.py`; they refuse before dispatch or input.
- Prior F1–F3 concerned keyboard focus receipts, launch-window association,
  and CLI cancellation status, outside this geometry/accessibility slice. This
  audit did not revalidate those paths and makes no claim about their current
  status.
- Fractional-scale seams, monitor transforms, negative coordinates, crop and
  resize metadata, hidden/stale capture behavior, mark age/class/size checks,
  and the normal AT-SPI extent and tree paths had no reproduced defect in the
  focused tests. `logical_rect` swaps axes for odd transforms; screenshot
  metadata reports the actual image dimensions and scale used to map pixels
  back to global logical coordinates.
- Malformed AT-SPI application replies are partly normalized: invalid extents,
  role values, missing children/state, and interface errors are dropped or
  treated as absent. The decoder enforces D-Bus message structure and size;
  no realistic, legal AT-SPI reply that escapes as an uncaught exception was
  demonstrated. This was a protocol-fixture review, not an adversarial live
  D-Bus application test.
- Hidden window captures carry `visible=false`; stable capture returns
  `stable=None` for them because a frozen hidden buffer cannot prove freshness.
  Window capture checks the session lock before using `grim -T`; region and
  monitor capture use screen capture, with the lock-screen pixels expected
  from the compositor. No locked live desktop was used to independently test
  compositor behavior.
- Timeout and descriptor handling: `grim` and `busctl` use `subprocess.run`
  with 10-second timeouts (which collects/closes pipes), while the AT-SPI wire
  connection has bounded call timeouts, closes on a timeout/broken connection,
  and caches connections for reuse. No descriptor leak was demonstrated; no
  stress/long-lived live-bus test was run.

## Validation and limits

Command:

```text
cd /workspace/omnimcp && .venv/bin/python -m pytest -q tests/test_pointer_quantization.py tests/test_zoom.py tests/test_screenshot.py tests/test_a11y.py tests/test_marks.py
183 passed in 0.47s
```

An initial run without escalation had 182 passed and one environment failure:
`private_paths` refused the sandbox's untrusted `/tmp` root while the zoom
test packaged its screenshot. The parent authorized escalation for focused
private-path tests; the command above then passed. This was an execution
environment restriction, not a product finding.

The isolated fanout command used `.venv/bin/python` with an in-memory fake Bus;
no files were created. Repository HEAD stayed at the target commit and
`git status --short` was empty. No dedicated geometry VM or live compositor
validation was performed, so monitor transform conventions and lock-screen
capture behavior are supported by source/tests only.
