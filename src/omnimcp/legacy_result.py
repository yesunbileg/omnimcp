"""Typed outcomes for legacy desktop text while preserving their wire strings."""


class LegacyFailure(str):
    """Legacy result whose source explicitly knows the requested check failed."""


class LegacyUnverified(str):
    """Legacy result whose dispatch happened but whose effect remains unknown."""


class LegacyContent(list):
    """Legacy MCP content carrying outcome metadata outside its unchanged wire blocks."""

    def __init__(self, content, outcome: str):
        super().__init__(content)
        self.outcome = outcome
