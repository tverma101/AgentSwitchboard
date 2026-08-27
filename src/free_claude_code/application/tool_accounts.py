"""Application boundary for installed Codex helper accounts."""

from typing import Any, Protocol


class CodexToolAccountError(RuntimeError):
    """A Codex tool-account operation could not complete safely."""


class CodexToolAccountsPort(Protocol):
    """Credential-free operations for installed Codex/helper accounts."""

    def status(self) -> dict[str, Any]: ...

    def select(self, profile: str) -> dict[str, Any]: ...

    def refresh_usage(self, profile: str) -> dict[str, Any]: ...

    def refresh_all_usage(self) -> dict[str, Any]: ...

    def forget(self, profile: str) -> dict[str, Any]: ...
