# Codex native account usage

Capability ID: `codex.usage` (read-only compact catalog).
Legacy MCP tool: `codex_usage` (also available in read-only mode).
Purpose: return account quota usage without model generation or credential copying.
Implementation: `src/omnimcp/codex_usage.py`; compact registration:
`src/omnimcp/adapters/codex.py`.

```bash
# Direct CLI, no worker required:
omnimcp codex-usage --timezone Asia/Ulaanbaatar

# Compact profile, after the worker has loaded the updated package:
omnimcp discover --action codex.usage
omnimcp observe codex.usage --params '{"timezone":"Asia/Ulaanbaatar"}'
```

MCP call: `codex_usage({"timezone":"Asia/Ulaanbaatar"})`.
Input: `timeout_s` (default 25, range greater than 0 through 60 seconds),
`timezone` (IANA zone, default empty = system local time).
Output: `status`, UTC `checked_at`, selected `timezone`, and `limits` containing
`limit_id`, `plan_type`, and `windows`. Each window reports `kind`, duration in
minutes, used/remaining percent, Unix reset and UTC/local ISO reset timestamps.
300-minute windows are `five_hour`, 10080-minute windows `weekly`, and other or
unknown durations `other`. Missing windows stay absent and missing resets stay
null. This is an account snapshot, not a local token counter or a reservation.

The installed `codex` is found through PATH, then `~/.local/bin/codex`.
The inherited environment/profile and existing native sign-in apply. A short-lived
`codex app-server --stdio` child performs only `initialize`, `initialized` and
`account/rateLimits/read`. It is reaped after the request, including on timeout.
No prompts, model invocation, tool execution, automatic login or scheduler is added.
Existing Codex processes are not signaled. Backend stderr/error text and arbitrary
response fields are omitted; output is bounded to 1 MiB before normalization.

Failures use `invalid_params`, `missing_dependency`, `timeout`, `auth_required`
(for explicit authentication codes), `backend_error`, `invalid_response` or
`unavailable`. API-key-only accounts or unsupported Codex versions may not expose
native account windows; quota availability is not inferred. A fresh MCP connection
is required to discover a newly installed tool. An already running compact worker
keeps its existing catalog until restarted; the direct CLI and legacy tool do not
need that worker.

Verification: `pytest tests/test_codex_usage.py`; fixtures do not use the real
account. Fresh stdio discovery/call and native-login smoke checks are separate
from fixtures. No token savings are claimed from output-byte measurements alone.
