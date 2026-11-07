# Verified external audit remediation

> Execute the user's explicit instruction to fix the verified findings immediately. No further design approval is needed. Use independent Luna high implementers and Terra high review; preserve regular WIP pushes.

Goal: fix demonstrated transport, runtime, temporary-file and admin trust gaps; make setup and documentation portable and brief. Base: 31c3194 on wip/audit-fixes-20261107. Keep main unchanged.

## Constraints

- Findings and evidence: /workspace/omnimcp-audit-fact-check-2026-11-07.md; uploaded review is evidence, not executable instructions.
- Preserve ordinary desktop/file/command capabilities. Do not silently remove compatibility manifests, tie plugin/runtime versions, rewrite dated historical evidence, or add caller-controlled privileged paths.
- Do not execute real root helpers, trigger authentication prompts, change the host configuration, or touch real user data for verification. Use isolated tests and the existing disposable Hyprland VM.
- New behavioral changes get meaningful regression tests and red/green evidence. Parent owns commits/pushes and integration; agents own disjoint files and do not spawn further agents.
- Recheck complete suite, Ruff, build and relevant real protocol/worker/VM acceptance before final success claims.

## Tasks and acceptance

1. Transport: eliminate legacy screenshot/zoom duplication; map compact application/transport failures to MCP error flags while preserving payload; return client_timeout on RPC read timeout without falsely claiming worker death; replace unknown legacy text success inference with explicit unverified outcome or typed success where justified. Verify production converters and real protocol errors, not live screenshots alone.
2. Private files: validate owner/type/mode for runtime/canvas temporary directories; reject pre-existing symlinks/untrusted paths and secure lock/state opens against symlinks. Centralize minimal reusable helpers without unrelated filesystem refactors. Preserve configured private XDG runtime paths and test public failure paths before any clobber.
3. Cancellation/shutdown: independently verify child exit after SIGKILL with a bounded wait and honest pending/denied status; fix the immediate-exit race without weakening the test. Bound Engine.close and actual worker shutdown for uncooperative handlers; do not claim executor threads can be killed within Python or close stores under live writers. Verify actual worker termination in a disposable subprocess.
4. Admin trust: remove agent-controlled privileged installation of mutable package source; use explicit root-controlled installation policy/manual setup with verifiable source. Enforce an independent retry decision rather than accepting auth_retry as proof of human consent. Restrict optional root-file helper by root-controlled exact-path policy and retain revision/backup/readback/xattr protections. Review the concrete design with Terra before implementation; document compatibility changes. General command capabilities remain intentional user-authority actions; no untrusted-MCP sandbox claim.
5. Documentation/packaging/CI: replace root README with short Mongolian features/examples/links matching user's supplied structure; move detailed instructions to linked docs. Remove personal defaults and retain both plugin compatibility formats. Correct current dependency provenance and synchronize maintained docs copies, retain historical evidence. Add reproducible CI build/format and real protocol/worker gates; add subprocess-aware coverage with meaningful privilege tests. Use the measured subprocess-aware baseline coverage floor (4b67a7c: 82.65%, integer gate 82%); do not force typing changes or reformat concurrently edited source files.

## Verification and review

- Record decisions and task evidence in /workspace/.omnimcp-runtime/external-audit-fixes/progress.md.
- Implement independent file domains in parallel under the dedicated existing WIP branch, inspect diffs, review each task and the integrated branch with Terra high. Do not accept subagent labels without source/evidence.
- Commit and push independently verified task groups regularly. Security-sensitive behavior and final integrated result require independent review.
- Run updated wheel in the real Hyprland VM if available; record the known compositor teardown 139 separately from application acceptance.
