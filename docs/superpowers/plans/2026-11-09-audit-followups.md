# Audit follow-ups implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Implementation stays with the primary agent, as requested by the user.

**Goal:** Correct the verified packaging/documentation findings and add explicit artifact retention maintenance.

**Architecture:** Preserve the OmniMCP product, Python module and commands; use the distinct `OmniMCP-linux` distribution name. Keep raw evidence in Git, outside distribution archives. Artifact cleanup is offline, previews by default, and requires `--apply`; it shares the worker's exclusive state lock.

**Tech stack:** Python 3.11+, SQLite, POSIX directory descriptors/flock, Hatch, pytest, uv.

**Spec:** The user's six-item review and the concrete decisions described above. Existing instructions authorize direct implementation and pushes to main.

## Global constraints

- No historical evidence rewrites, PyPI publishing or user data cleanup during validation.
- No automatic deletion or changes to job/auth/process records, backups or journals.
- Retention defaults: 30 days and 1 GiB of registered artifact bytes; oldest first.
- This is a retained-file maintenance budget, not a hard quota on live subprocess output or the SQLite database.
- Refuse cleanup while a worker owns the state lock or unresolved jobs/processes remain.

## Review focus

- Symlink/hardlink or corrupted artifact paths must not touch external files.
- Lock ownership and unfinished work must prevent deletion.
- Dry-run and read-only policies must preserve data.
- Expired references must keep returning `expired_artifact` rather than silently changing IDs.
- Distribution changes must leave both command aliases and VM wheel paths functional.

### Task 1: Distribution and documentation

- [x] Change distribution metadata to `OmniMCP-linux`, refresh lock, preserve both commands and `omnimcp` imports.
- [x] Exclude `/docs/evidence` from sdist; inspect the actual wheel and tarball.
- [x] Repair changelog structure, audit integration status, links and default-profile architecture wording.
- [x] Add a testing guide: umask 022 full suite, coverage floor 84, live markers only inside an isolated Hyprland VM.

### Task 2: Offline artifact maintenance

- [x] Add failing real-filesystem tests in `tests/test_artifact_retention.py` for preview/apply, age/size, expired refs, lock contention, unfinished work, malicious paths and CLI policy.
- [x] Implement `prune_artifacts(root=None, *, older_than_days=30, max_bytes=1073741824, apply=False)` in `core/retention.py`.
- [x] Add `OmniMCP worker prune` options in `core_cli.py` and document boundaries.
- [x] Run focused tests, full suite with subprocess coverage under umask 022, Ruff and artifact inspection.
- [x] Review the final diff and report live-test limits explicitly.

Delivery: commit/push after the checks recorded in [the validation report](../../audits/2026-11-09-followups-validation.md).
