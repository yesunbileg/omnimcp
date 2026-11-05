# Codex usage local validation — 2026-10-29

Scope: selected self-learing-os proposal 1 only, native Codex account quotas.
No MemOS health/backup automation, model/provider changes or scheduled jobs.

- Full unit/integration suite: 1153 passed, 16 live GUI tests deselected (14.68s).
- Feature fixtures include JSONL handshake, multiple buckets/deduplication,
  missing/null windows, UTC/local resets, malformed/oversized output, invalid
  fields, timeout and child reaping, error sanitization and read-only contracts.
- Real stdio transport with synthetic Codex executable: discovery and call passed;
  exactly one text content block, no duplicated structured result.
- Installed plugin shim, fresh stdio connection and real native login:
  `codex_usage` discovered among 16 tools; call passed in 1.087s, 1.668s including
  connection; output 529 UTF-8 bytes. No generation invocation.
- Same separate live response comparison: raw API payload 1237 bytes; normalized
  helper payload 529 bytes (57.2% smaller). This compares output bytes, not tokens
  or model latency. No before/after speedup is claimed.
- CLI supports `agentic-os-mcp codex-usage --timezone Asia/Ulaanbaatar`.
- Five installed files equal source SHA-256 hashes; backed-up original hashes valid.

Local installation is a selective patch to the existing 0.2.0 uv tool, not a
published release or Git commit. Only `codex_usage.py`, `adapters/codex.py`,
`adapters/__init__.py`, `cli.py` and `legacy_transport.py` were installed. The
existing dirty source tree was preserved. Source docs/tests stay in this checkout.

Verified private patch backup and guarded rollback:

```bash
python /home/home/.local/state/agentic-os-mcp/local-patches/codex-usage-20261028T221028Z/restore.py
```

The rollback refuses if patched installed files have changed since deployment.
Reconnect MCP after rollback or installation to load that code/tool schema.
The current Codex connection was not killed/restarted; its already loaded tool
list does not gain this tool automatically. Direct CLI works immediately. A
previously running compact worker keeps its old catalog until a safe restart;
that live daemon was not restarted. Fresh compact registry discovery and fixture
handler calls are tested independently.
