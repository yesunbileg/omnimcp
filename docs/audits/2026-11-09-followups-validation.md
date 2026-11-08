# Packaging and retention follow-ups — 2026-11-09

Base: `5d8ca326444b38cb12e97d8be21f1d1bb0acc95a`. These results cover the
follow-up changes, not a new live Hyprland validation.

- `4b277c0` is an ancestor of main; audit integration status, changelog,
  profile architecture and documentation links were corrected.
- PyPI's `omnimcp` belongs to the unrelated milkymap/omnimcp router project.
  The distinct distribution is `OmniMCP-linux`; product, command aliases,
  Python imports and state paths remain compatible. Nothing was published.
- A fresh sdist contains no `docs/evidence` entries; raw evidence remains in Git.
  Wheel metadata and both console entry points were inspected. The wheel was
  installed into a fresh environment outside the checkout; both command aliases,
  legacy/compact MCP initialization and retention preview were exercised.
- Terra's read-only review found legacy process identities/startup locking and
  persisted worker-policy gaps. Nine failing regression cases reproduced these
  paths and malformed/symlinked policy, then passed after one fix pass. The
  revised patch was verified directly; no second independent approval is claimed.
- An actual worker started from the final wheel persisted read-only policy.
  After shutdown, a normal-shell prune preview succeeded, apply was refused,
  and the fixture artifact bytes remained intact.
- Full suite under `umask 022`, with worker/CLI subprocess coverage:
  **1,523 passed, 16 deselected**, **85.01%** coverage; the new floor is 84%.
  Ruff check, Ruff format check, diff whitespace check, wheel/sdist build and
  VM runner shell syntax check passed.

Retention is explicit offline maintenance: preview first and `--apply` for
deletion. It preserves metadata, jobs/events/auth state, backups and journals.
It does not add automatic deletion, a hard live-output/database quota or secure
erasure. Raw historical evidence was not rewritten. The 16 live pytest cases,
polkit approval and new full-VM lifecycle validation were not executed here.
