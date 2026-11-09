# Product and file-safety audit report

Target: `/workspace/omnimcp`, HEAD `eaabe434519a291dd5f8108014fe7186570e5418`. Read-only review; no source, test, Git, or external-service changes. The two candidates below were not listed in the inspected historical audits (`docs/audits/2026-11-07-review.md`, `2026-11-08-remediation-validation.md`, `2026-11-09-followups-validation.md`, and `docs/AUDIT-2026-10-24.md`).

## Confirmed candidates

### P2 candidate — Kanban `append_text` is stored in the journal verbatim

**Source / invariant:** `src/omnimcp/journal.py:274-292` redacts only dictionary values under the exact key `text`; `src/omnimcp/server.py:2730-2749` records `kanban_update` with a free-form `append_text` parameter used for result lines; `docs/settings.md:30-31` describes `OMNIMCP_JOURNAL_TEXT` as the explicit opt-in to retain written/copied text and warns it can include passwords. `docs/features.md:45-47` and `docs/help.md:40` describe `append_text` as arbitrary appended notes. With journal recording enabled and text recording off (the default), private notes supplied through this field are persisted in plain text in the local journal. The exact-key implementation digests `text` but leaves this semantically equivalent free text untouched.

**Reproduction:** From `/workspace/omnimcp`:

```sh
env -u OMNIMCP_JOURNAL_TEXT PYTHONPATH=src .venv/bin/python - <<'PY'
import json, os, tempfile
from pathlib import Path
from omnimcp import journal
root = Path(tempfile.mkdtemp(prefix='journal-product-repro-', dir='/workspace/.omnimcp-runtime/audit-ac-2026-11-09/product'))
os.chmod(root, 0o700)
os.environ['OMNIMCP_JOURNAL'] = str(root / 'journal.ndjson')
secret = 'private clinical follow-up: diagnosis and phone 555-0108'
journal.record('kanban_update', 'act', {'task_id':'fixture', 'append_text': secret}, 'ok', 1)
journal.record('kanban_update', 'act', {'task_id':'fixture', 'text': secret}, 'ok', 1)
raw = (root / 'journal.ndjson').read_text()
print(raw.strip())
print('append_text plaintext:', secret in json.loads(raw.splitlines()[0])['args']['append_text'])
print('text plaintext:', secret in json.dumps(json.loads(raw.splitlines()[1])['args']['text']))
PY
```

Output showed `append_text` containing the complete note and `append_text plaintext: True`; equivalent `text` was `{"redacted":true,"chars":56,"sha256":"7896a78e9b06"}` and `text plaintext: False`. This isolates the production `record`/`redact` path; it does not invoke a real Kanban board or capture real user data.

**Root cause / minimal fix:** Redaction treats a parameter name as a complete classification of free-form text. Digest `append_text` by default too (prefer a centralized set of sensitive free-text argument names, used recursively); retain the existing opt-in behavior consistently if replay requires literal content. Add a regression that journals both `text` and `append_text` with the opt-in unset.

**Limits:** Journaling is itself opt-in (`OMNIMCP_JOURNAL` defaults off), and the destination is private by design. The issue is unintended plaintext persistence once journaling is enabled. `OMNIMCP_JOURNAL_TEXT=1` explicitly opts into literal typed/copied text; the field-specific exception here bypasses that opt-in. I found no earlier audit reporting this parameter gap.

### P2 candidate — Canvas reports a symlink as a verified backup, then edits away the original

**Source / invariant:** `src/omnimcp/canvas.py:322-332` treats `FileExistsError` for the revision-derived backup name as acceptable if `backup.read_bytes() == raw`. It does not require the existing backup to be a regular file. `src/omnimcp/server.py:2874-2876` and `docs/features.md:71-75` promise a verified/private backup before atomic replacement. A symlink at the backup name pointing to the original Canvas passes byte comparison. Once `os.replace` replaces the original file, that same symlink resolves to the new content; the returned backup receipt is false and the old content is no longer backed up.

**Reproduction:** Created an isolated mode-0700 fixture under the assigned audit directory. The backup path was a symlink to the fixture Canvas. Called `canvas._write(path, raw, edited_doc, revision)`.

Output:

```text
returned backup: /workspace/.omnimcp-runtime/audit-ac-2026-11-09/product/canvas-backup-repro-upc_v712/.fixture.canvas.834753452fa05f5923aa8c75883a1f2884dc99f9e029712a0b971b7d015b1c8a.bak
backup is symlink: True
target text: after
backup text: after
```

The tool returned success with the backup path, but reading it produced the edited state (`after`) instead of the original (`before`). This used a synthetic temporary file only. The first run hit the sandbox's `private_paths` rejection of `/tmp` as an untrusted filesystem root; the same bounded fixture succeeded when run with the permitted escalation and made no host/user-file changes.

**Root cause / minimal fix:** Existing-name verification follows symlinks and checks bytes only. Require an existing backup to be a non-symlink regular file opened with `O_NOFOLLOW`, then verify through the opened descriptor; if it is not a valid backup, refuse before replacement. Consider verifying identity and mode as well as bytes.

**Limits:** The repro demonstrates false backup success when the deterministic hidden backup name already exists as a symlink to the source. It does not establish a cross-user exploit or imply Canvas path resolution itself is unsafe; the user explicitly selects the Canvas file. No prior audit described this backup-name symlink case.

## Rejected hypotheses and scope notes

- Canvas and Kanban resolve/read an explicitly selected user file; this is an intended file capability. Kanban's configured path rejects symlink replacement with `O_NOFOLLOW`; Canvas resolves the supplied path and uses a regular-file descriptor check. I did not classify path selection itself as a traversal vulnerability.
- The Canvas external-editor check has a documented gap between its final revision read and `os.replace` (`canvas.py:341-344`); docs explicitly acknowledge that external editors do not share the lock and can race. I did not report that documented residual race as a new defect.
- OpenCode delegation runs under the user's authority and is explicitly documented as not being an OS sandbox (`docs/features.md`, `docs/CORE.md`). I did not treat that intentional capability as a vulnerability.
- Codex usage subprocess protocol handling and skill install/uninstall contracts were reviewed at source/docs level; I did not confirm an additional finding in those areas. No live account, real CLI login, or real home-directory install/uninstall was exercised.
- No tool-schema or false-success defect was confirmed beyond the Canvas backup receipt above.

## Focused checks and limits

- Initial focused run, `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_journal.py tests/test_canvas.py tests/test_kanban.py`: **75 passed, 5 failed**. Each of the five failures stopped at `private_paths._open_parent` rejecting `/tmp` with `PermissionError: untrusted filesystem root`; one was a child-server startup failure for the same reason. This managed environment's `/tmp` is owned by `nobody:nogroup`, while the code permits only root-owned trusted `/tmp`. This first result is retained as environment-only evidence.
- Reran the five affected Canvas node IDs with `XDG_RUNTIME_DIR` and `TMPDIR` both set to the private audit fixture directory and the permitted sandbox escalation: **5 passed in 0.75s**. The successful rerun covered verified backup roundtrip, semantic card/connection edits, concurrent change refusal, CLI read path, and stdio read/edit roundtrip. No source or test files were changed.
- The journal reproduction succeeded without elevation. The Canvas symlink reproduction succeeded under escalation after the sandbox rejected `/tmp`; its runtime/temp fixture was contained in the assigned private audit directory.
- No full test suite, actual desktop, external service/account, actual user file, or packaging install was tested. Scope is source/contract review, focused journal/Canvas/Kanban tests, and two bounded synthetic reproductions.
