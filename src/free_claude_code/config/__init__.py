"""Configuration management."""

from typing import Any

__all__ = ["Settings", "get_settings"]


def __getattr__(name: str) -> Any:
    """Load settings only when callers access the package exports."""

    if name == "Settings":
        from .settings import Settings

        return Settings
    if name == "get_settings":
        from .settings import get_settings

        return get_settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
