# OmniMCP Audit Repair Implementation Plan

> **For autonomous workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. User explicitly selected GPT-6 Luna implementations and leader follow-up repairs.

**Goal:** Repair confirmed omnimcp defects without losing the existing dirty working tree or disrupting the user desktop.

**Architecture:** Retain the current legacy/compact profiles, worker architecture and strict schemas. Make narrowly scoped corrections with failing regressions, then review the combined changes and verify both source and installed behavior.

**Tech Stack:** Python >=3.11, Pydantic, pytest, Ruff, MCP, Unix sockets, Hyprland, user systemd, uv.

**Spec:** User request on 2026-10-24: full omnimcp audit, GPT-6 Luna repairs, leader fixes for remaining issues; provided AGENTS.md applies. Audit evidence in docs/AUDIT-2026-10-24.md.

## Global Constraints

- Preserve all pre-existing tracked/untracked edits and deletions; do not commit the user baseline.
- Backup: /home/home/.cache/omnimcp-audit/20261024-014854/baseline.tar.gz with manifest.json.
- No compositor/Caelestia configuration edits or restart. No real package/network/disk/power/admin mutations as tests.
- Latest AGENTS.md: admin entry uses a graphical popup only; do not ask again after cancellation/closure.
- Screenshots preserve the user tab/workspace/focus immediately.
- Latest AGENTS.md: use Playwright as primary for Brave automation; UI only when strictly necessary. Backend integration tests use private fixtures.
- Implementation model is gpt-6-luna for longer coding tasks; leader fixes small issues immediately and takes over immediately if a subagent repeats the same mistake a second time, per latest AGENTS.md.
- Red/green regressions precede production fixes. Full project suite is required after integration.
- No push, publication, merge or unrelated dependency upgrades.

## Review Focus

- A workflow containing references must still reject unknown/missing/incorrect static fields before any mutation.
- Dynamic values remain runtime-validated; legitimate nested references and local assertion/wait result paths must work.
- File undo/move must preserve changed content, stale source replacements and an existing destination.
- Named-seat uncertainty must fail before text reaches the default seat.
- Concurrent captures must retain distinct bytes, including when wall-clock values match.

### Task 1: Validate workflow requests before side effects

**Files:** Modify src/omnimcp/core/engine.py, optionally core/registry.py; Test tests/test_core.py.
**Interfaces:** Registry Action models validate resolved values; Engine.validate_workflow validates static structure; when paths address prior results, assert/wait paths address the current result.

- [x] Add regressions with an earlier marker-writing step and later unknown/missing/wrong static params alongside a legitimate $ref. Assert rejection and no marker/job execution.
- [x] Add regressions for future/self/unknown `when` roots and invalid references in condition equals; preserve valid local assert/wait paths and current-result assertion references where supported.
- [x] Run regressions and record expected failures.
- [x] Implement static validation without inventing permissive typed placeholder values; retain runtime validation for resolved references.
- [x] Run focused core/worker tests and full suite; record exact commands/results in repair ledger.

### Task 2: Preserve files during undo and move

**Files:** Modify src/omnimcp/adapters/files.py; Test tests/test_native_adapters.py or a dedicated file regression test module.
**Interfaces:** file.write returns revision-guarded file.restore undo; file.move preserves destination and returns verified receipt or explicit stale/failure state.

- [x] Add failing tests for undo of a newly created file and refusal if the new file was subsequently changed.
- [x] Add deterministic failing concurrent source-replacement test during move; assert the replacement bytes survive, destination is never overwritten, and no false verified success is returned.
- [x] Implement revision-checked creation undo under the file lock, with fsync/readback and an accurate receipt.
- [x] Implement safe no-overwrite move semantics; do not claim an atomic guarantee from a path check followed by unlink. If safe rollback cannot return a changed file to its source, retain the bytes and report their location.
- [x] Test unchanged move/undo, destination exists, stale source, same-path refusal and relevant metadata behavior. Run focused file/core tests and full suite.

### Task 3: Keep input on its intended seat and captures distinct

**Files:** Modify src/omnimcp/input.py and server.py; Test tests/test_input.py / tests/test_input_safety_protocol.py / tests/test_screenshot.py.
**Interfaces:** Existing keyboard and screenshot tools retain their signatures and error/status conventions.

- [x] Add a failing named-seat query WireError regression proving `_wtype` receives no text; preserve normal default-seat behavior.
- [x] Fail closed when an explicitly configured seat cannot be established; verify keyboard helper paths that share seat routing.
- [x] Add a failing same-clock screenshot packaging regression: distinct paths and original bytes remain readable.
- [x] Use exclusive unique private screenshot files and cleanup on write failure; preserve metadata and image-only modes.
- [x] Run focused input/screenshot/safety regressions and full suite.

### Task 4: Leader review, remaining repairs and runtime verification

**Files:** src/omnimcp/session.py (two existing E501 fixes), docs/AUDIT-2026-10-24.md; additional source changes only for reproduced remaining defects.
**Interfaces:** Local installed distribution and active worker must be distinguished from source; same-version installed server.py is currently stale relative to pre-task source safety changes.

- [x] Leader reviews task diffs against the external baseline manifest; resolve all confirmed remaining defects using failing tests first.
- [x] Correct two E501 lines without behavior changes and run whole-repo Ruff.
- [x] Address the dependency advisory audit with targeted compatible updates (MCP 1.x and affected locked TLS/JWT dependencies), run full regressions, and repeat advisory scan. Record any advisory lacking a fixed release or unexercised path explicitly; do not claim zero vulnerabilities merely from filtering.
- [x] Independent whole-change review; record spec and quality verdicts. Do not represent unverified findings as fixes.
- [x] Run full unit suite, safe live e2e suite, build wheel/sdist, and verify package contents.
- [x] If deployment is authorized, update user-local installation with tested locked dependencies; check active jobs before a worker restart, preserve worker policies/configuration, and verify adopted source hashes.
- [x] Re-run installed MCP smoke with only temporary files, own transient service/window, preserving user focus. Record skipped integration gates and pending client reconnect honestly.
- [x] Deliver concise outcome and link the audit evidence. Keep source changes reviewable; do not commit the pre-existing dirty tree.

Completed after user approval. Longer tasks implemented by GPT-6 Luna/high; leader handled small and repeated mistakes under latest AGENTS.md. Final source1143 passed; installed ext4/NTFS3 and desktop/browser MCP gates passed. Changes kept in approved checkout with no commit/merge/push. See docs/AUDIT-2026-10-24.md for evidence and explicit limits.
