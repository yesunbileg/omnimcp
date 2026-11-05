"""Read-only native Codex account quota capability."""

from agentic_os_mcp.codex_usage import read_usage


def usage(ctx, timeout_s: float = 25, timezone: str = "") -> dict:
    """Codex account usage, remaining percentages and reset times; no generation."""
    return read_usage(timeout_s, timezone)


def register(registry):
    registry.add(
        "codex.usage",
        usage,
        readonly=True,
        idempotent=True,
        verification="Native account/rateLimits/read; unavailable windows are not inferred.",
        example={"timezone": "Asia/Ulaanbaatar"},
    )
