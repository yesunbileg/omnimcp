# Source and backend provenance

No new donor code was copied for this change. Registry, worker, persistence,
workflows and native wrappers are local Python implementations.

| Source/backend | Version/commit | License | Use and reason |
| --- | --- | --- | --- |
| https://github.com/IlyasKhallouki/hypruse | original checkout HEAD `efce06d2cb91ccea48d34b6321de78b1603312d8` | MIT, retained LICENSE | Existing customized desktop code; local rename/Canvas/Kanban work preserved. No upstream merge performed. |
| https://github.com/modelcontextprotocol/python-sdk | `mcp==1.28.1`, uv.lock | MIT | Existing MCP protocol dependency pinned for compatibility. |
| https://github.com/giampaolo/psutil | `7.2.2`, uv.lock | BSD-3-Clause | Direct process identity and native measurements dependency; no source copied. |
| https://github.com/microsoft/playwright-mcp | optional `@playwright/mcp@0.0.83`; user-local package-lock records transitive integrity | Apache-2.0 | Unmodified lazy browser backend through standard MCP. No donor code. |
| https://github.com/restic/restic | host-installed optional CLI, version reported by its executable | BSD-2-Clause | Unmodified backup backend, activated only with configured repository/credentials. |

DesktopCommanderMCP and Cockpit from the planning document were architectural
references only; no files or excerpts were imported. pyroute2 is not added because
the implemented wrappers use existing `ip`, NetworkManager and native CLIs; an
adapter needing Netlink can add it as a scoped dependency later. System CLI tools
are invoked, not redistributed. Their installation and licenses remain upstream.

If future work copies donor code, add its exact source URL, immutable commit,
license, destination paths and the reason for modification here before shipping.

The baseline archive of the dirty working tree was created outside the checkout at
`~/.local/state/agentic-os-mcp-baselines/20261021-192742/` with source SHA-256,
Git diff/status, original HEAD and installed dependency versions. It includes the
pre-existing uncommitted files and excludes the virtualenv and top-level tool caches. The
baseline is host-local recovery evidence, not part of a distributable package.
