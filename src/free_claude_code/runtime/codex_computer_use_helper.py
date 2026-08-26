"""Approved-helper adapter for the managed Codex Computer Use host."""

import threading
from collections.abc import Mapping
from typing import Any

from free_claude_code.application.capabilities import Capability
from free_claude_code.application.helpers import ApprovedHelper
from free_claude_code.runtime.codex_computer_use import (
    COMPUTER_USE_METHODS,
    CodexComputerUseError,
    CodexComputerUsePaths,
    resolve_official_computer_use,
)
from free_claude_code.runtime.codex_computer_use_managed import ElicitationHandler
from free_claude_code.runtime.codex_computer_use_native_contract import (
    ContractCheckedManagedCodexComputerUseBroker,
)

CODEX_COMPUTER_USE_HELPER_ID = "codex-computer-use"
CODEX_COMPUTER_USE_PROVIDER_FAMILY = "computer"
DEFAULT_COMPUTER_USE_OUTPUT_BYTES = 2 * 1024 * 1024
READ_ONLY_COMPUTER_USE_METHODS = frozenset({"list_apps", "get_app_state"})
MUTATING_COMPUTER_USE_METHODS = frozenset(COMPUTER_USE_METHODS) - (
    READ_ONLY_COMPUTER_USE_METHODS
)


class CodexComputerUseHelperAdapter:
    """Own one warm native-contract-checked broker for the generic helper seam."""

    def __init__(
        self,
        *,
        paths: CodexComputerUsePaths | None = None,
        elicitation_handler: ElicitationHandler | None = None,
    ) -> None:
        self._paths = paths
        self._elicitation_handler = elicitation_handler
        self._broker: ContractCheckedManagedCodexComputerUseBroker | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            broker = self._broker
            self._broker = None
        if broker is not None:
            broker.close()

    def execute(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]:
        """Run one native operation and propagate helper cancellation to app-server."""

        if operation not in COMPUTER_USE_METHODS:
            raise CodexComputerUseError(
                f"unsupported Computer Use helper operation: {operation}"
            )
        if cancel_event.is_set():
            raise CodexComputerUseError("Computer Use helper cancelled before dispatch")

        broker = self._get_broker()
        finished = threading.Event()

        def cancel_watcher() -> None:
            while not finished.wait(timeout=0.05):
                if cancel_event.is_set():
                    broker.close()
                    return

        watcher = threading.Thread(
            target=cancel_watcher,
            name="fcc-codex-computer-use-cancel",
            daemon=True,
        )
        watcher.start()
        try:
            result = broker.call(operation, arguments)
        finally:
            finished.set()
            watcher.join(timeout=0.2)

        return result

    def controller_guidance(self) -> str:
        """Return the installed official Computer Use skill for session-start injection."""

        return self._get_broker().native_skill.text

    def parity_receipt(self) -> dict[str, object]:
        """Return content-free native schema/skill evidence for certification."""

        return self._get_broker().parity_receipt()

    def approved_helper(
        self,
        *,
        max_output_bytes: int = DEFAULT_COMPUTER_USE_OUTPUT_BYTES,
    ) -> ApprovedHelper:
        """Return deterministic #30/#104 metadata bound to this adapter."""

        return ApprovedHelper(
            helper_id=CODEX_COMPUTER_USE_HELPER_ID,
            provider_family=CODEX_COMPUTER_USE_PROVIDER_FAMILY,
            capabilities=frozenset(
                {
                    Capability.SEMANTIC_MACOS_CONTROL,
                    Capability.PIXEL_COMPUTER_USE,
                    Capability.SCREENSHOT_VISION,
                }
            ),
            execute=self.execute,
            local=True,
            billable=False,
            max_output_bytes=max_output_bytes,
            mutating_operations=MUTATING_COMPUTER_USE_METHODS,
        )

    def _get_broker(self) -> ContractCheckedManagedCodexComputerUseBroker:
        with self._lock:
            broker = self._broker
            if broker is not None and broker.started:
                return broker
            paths = self._paths or resolve_official_computer_use()
            broker = ContractCheckedManagedCodexComputerUseBroker(
                paths,
                elicitation_handler=self._elicitation_handler,
            )
            broker.start()
            self._broker = broker
            return broker


__all__ = [
    "CODEX_COMPUTER_USE_HELPER_ID",
    "CODEX_COMPUTER_USE_PROVIDER_FAMILY",
    "MUTATING_COMPUTER_USE_METHODS",
    "READ_ONLY_COMPUTER_USE_METHODS",
    "CodexComputerUseHelperAdapter",
]
