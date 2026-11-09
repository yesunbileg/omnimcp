# Core and privileged boundary audit

Base: `/workspace/omnimcp`, frozen HEAD `eaabe434519a291dd5f8108014fe7186570e5418`.
Scope: `root_helper.py`, `adapters/admin.py`, and `core/{worker,client,protocol,engine,retention}.py`; related process identity checks in `core/state.py` and `core/execution.py` were inspected to validate retention/shutdown boundaries. No repository source, test, or Git files were changed. No real helper elevation, host mutation, or ambient process signal was used.

## Findings

No confirmed P0–P3 runtime/security finding in the audited scope. Status: reviewed; no independent exploit reproduced.

The root-helper update path uses fixed production helper/policy/backup paths, canonical exact allowlist matching, descriptor-relative nofollow opens, ownership/mode checks, revision checks, private backup creation/readback, temp-file replace, and final digest verification (`src/omnimcp/root_helper.py:160-313`). Admin availability is advisory only; actual policy enforcement is repeated in the helper. The helper remains manually installed as intended.

The worker checks connecting peer UID (`src/omnimcp/core/worker.py:67-74`); the client checks socket inode owner/mode before connect (`src/omnimcp/core/client.py:35-45`). The custom socket parent is only checked for owner by the worker (`worker.py:49-52`), but the reviewed ownership check on the client endpoint and the explicit same-UID trust model did not yield a reproducible cross-UID request/response forgery. A parent writable by another UID can permit pathname denial of service; no reportable privilege escalation or confidentiality bypass was demonstrated from that condition.

Engine owner read-only/dry-run flags are ORed with caller readonly and checked at dispatch/execution (`src/omnimcp/core/engine.py:217-218,403-412,645-674`). Auth cancellation remains persisted and checked before another privileged attempt (`src/omnimcp/core/execution.py:90-103,179-204`); CLI auth reset shares the same local user authority, consistent with prior validation. Retention deletion requires offline lock/process checks and recorded worker policy (`src/omnimcp/core/retention.py:36-58,73-110,184-206`), and rechecks artifact inode metadata before unlink (`144-169`). Process recovery checks PID, process start time, and process group before signaling; loss/denial retains unresolved records rather than blindly signaling (`src/omnimcp/core/state.py:245-351,353-368`).

## Checks and limits

- `.venv/bin/pytest -q tests/test_root_helper.py tests/test_admin_hardening.py` → `28 passed in 0.64s`.
- Initial broad command: `.venv/bin/pytest -q tests/test_admin_hardening.py tests/test_artifact_retention.py tests/test_worker.py tests/test_process_recovery.py tests/test_auth_override_policy.py tests/test_private_paths.py` → `42 passed, 24 failed, 8 errors in 2.91s`. This run used default `/tmp/pytest-of-agent/...`; `private_paths._open_parent` rejected that fixture ancestor as `untrusted filesystem root`. Full output preserved in `broad-focused-initial-env.log`.
- Rerun with private TMPDIR/XDG and short pytest base: `TMPDIR=/workspace/.omnimcp-runtime/audit-ac-2026-11-09/core-security/tmp XDG_RUNTIME_DIR=/workspace/.omnimcp-runtime/audit-ac-2026-11-09/core-security/xdg-runtime .venv/bin/pytest --basetemp=/tmp/aac -q tests/test_admin_hardening.py tests/test_artifact_retention.py tests/test_worker.py tests/test_process_recovery.py tests/test_auth_override_policy.py tests/test_private_paths.py` → `74 passed in 5.26s`. The private-scratch-only attempt before shortening `--basetemp` had `72 passed, 2 errors` because those fixtures exceeded the AF_UNIX path length; its full output is preserved in `broad-focused-private-env.log`.
- The private runtime directories and `/tmp/aac` were mode 0700. The final rerun used the environment’s required unsandboxed execution to permit subprocess/private-path/Unix IPC fixtures. The rerun did not modify source or tests.
- No broader suite, real pkexec approval, privileged host setup, or live desktop validation was performed.
