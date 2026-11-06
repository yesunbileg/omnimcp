# Hardening continuation implementation plan

**Goal:** Complete the remaining A19/A20/A21 requirements from the supplied conversation against the already renamed `omnimcp` main branch.

**Architecture:** Preserve the seven compact MCP tools and use the authenticated local worker socket for owner control. Reuse verified process identity and group cleanup for cancellation and recovery. Migrate old environment names before module-level configuration reads.

**Tech stack:** Python >=3.11, existing uv.lock, pytest, MCP stdio, Unix sockets, psutil.

## Constraints and scope

- The rename has already landed; do not replay obsolete scratch-copy paths or rename the project again.
- Keep existing explicit new environment settings, including empty values; warnings contain names only and go to stderr.
- Only signal fixture processes or recorded job processes whose identities have been verified.
- Keep `worker stop` behavior; add `worker stop-all` outside MCP discovery/capability dispatch. A CLI interface is not an authorization boundary against an agent with shell access.
- Preserve the final A19 exception allowing tabs in command arguments.
- Validate with real worker/MCP/subprocess/file operations. Live Hyprland and polkit checks require a compatible host and remain unrun here.
- Commit and push independently validated changes to main as requested. Do not force push.

## Task 1: Runtime portability of existing validation tests

Files: `tests/test_validation_errors.py`.

- [x] Capture existing real subprocess failures caused by omitted XDG_RUNTIME_DIR.
- [x] Pass each test's private tmp_path explicitly into child environments; retain all validation/redaction assertions.
- [x] Run the complete file and commit/push the independent correction.

## Task 2: Trusted allowlist special files

Files: `src/omnimcp/server.py`, `tests/test_launch_allowlist.py`.

- [x] Reproduce a configured FIFO blocking before fstat in a bounded subprocess.
- [x] Add a regression and nonblocking open, preserving existing regular-file and ownership checks.
- [x] Run allowlist/auth tests, review, commit and push.

## Task 3: Preserve old owner settings

Files: `src/omnimcp/__init__.py`, `src/omnimcp/legacy_env.py`, `tests/test_legacy_env.py`, `docs/MIGRATION.md`.

- [x] Fail fresh-interpreter tests for old-only, conflicting/empty new settings, safe stderr, CLI help, and actual readonly MCP discovery.
- [x] Implement generic prefix migration at package import; write documented manual migration/rollback steps without touching user configuration.
- [x] Run tests and review packaging before commit/push.

## Task 4: Safe owner cancellation

Files: `src/omnimcp/core/{state,execution,engine,worker}.py`, `src/omnimcp/{core_cli,cli,safety}.py`, recovery tests and new stop-all tests.

- [x] Demonstrate normal cancellation leaking a TERM-ignoring descendant after its leader exits; test queued and blocked-handler stop-all behavior.
- [x] Share the verified group cleanup routine and coordinate cancellation races; never KILL a group based on a departed leader.
- [x] Implement local socket owner control and CLI counts: cancelled, groups_terminated, killed, threads_still_busy. Verify no MCP/act/workflow path exposes the control request.
- [x] Protect legacy beacon stop against PID reuse/unrelated processes if feasible within this change.
- [x] Run real integration tests, review signal sites, commit and push.

## Final validation

- [x] Run full pytest suite, full Ruff check, wheel/sdist builds, and verify no unintended files are tracked.
- [x] Exercise fresh worker startup and MCP round trips with independent file readback and process-exit checks.
- [x] Record actual outcomes, limitations, and remaining A17/A18/audit work without claiming those follow-up projects complete.
