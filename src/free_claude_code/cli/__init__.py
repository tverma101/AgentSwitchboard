"""CLI integration for installed launchers and managed Claude Code."""

from typing import Any

__all__ = ["ManagedClaudeSession", "ManagedClaudeSessionManager"]


def __getattr__(name: str) -> Any:
    """Load managed-session exports only when callers access them."""

    if name == "ManagedClaudeSession":
        from .managed import ManagedClaudeSession

        return ManagedClaudeSession
    if name == "ManagedClaudeSessionManager":
        from .managed import ManagedClaudeSessionManager

        return ManagedClaudeSessionManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
