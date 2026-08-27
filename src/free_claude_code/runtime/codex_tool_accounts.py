"""Runtime adapter for the installed Codex tool-account store."""

from collections.abc import Callable
from typing import Any

from free_claude_code.application.tool_accounts import (
    CodexToolAccountError,
    CodexToolAccountsPort,
)
from free_claude_code.cli import codex_accounts


class CodexToolAccountsRuntime(CodexToolAccountsPort):
    """Expose only safe Codex account operations to the local Admin API."""

    def status(self) -> dict[str, Any]:
        try:
            accounts = codex_accounts.list_accounts()
        except codex_accounts.CodexAccountError:
            return self._unavailable_status()
        return self._status(accounts)

    def select(self, profile: str) -> dict[str, Any]:
        self._run(lambda: codex_accounts.select_account(profile))
        return self.status()

    def refresh_usage(self, profile: str) -> dict[str, Any]:
        self._run(lambda: codex_accounts.refresh_usage(profile))
        return self.status()

    def refresh_all_usage(self) -> dict[str, Any]:
        outcomes = self._run(codex_accounts.refresh_all_usage)
        result = self.status()
        result["refresh_errors"] = dict(outcomes)
        return result

    def forget(self, profile: str) -> dict[str, Any]:
        self._run(lambda: codex_accounts.forget_account(profile))
        return self.status()

    @staticmethod
    def _run(operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except codex_accounts.CodexAccountError as exc:
            raise CodexToolAccountError(str(exc)) from exc

    @staticmethod
    def _status(accounts: tuple[codex_accounts.CodexAccount, ...]) -> dict[str, Any]:
        return {
            "available": True,
            "state": "ready",
            "storage": "$CODEX_HOME/auth.json",
            "profiles_storage": "$CODEX_HOME/accounts/profiles",
            "accounts": [account.public_dict() for account in accounts],
        }

    @staticmethod
    def _unavailable_status() -> dict[str, Any]:
        return {
            "available": True,
            "state": "error",
            "storage": "$CODEX_HOME/auth.json",
            "profiles_storage": "$CODEX_HOME/accounts/profiles",
            "accounts": [],
            "message": "Codex tool account storage needs attention.",
        }
