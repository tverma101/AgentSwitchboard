"""Tests for the #104 adapter around managed Codex Computer Use."""

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from free_claude_code.application.capabilities import Capability
from free_claude_code.runtime.codex_computer_use import (
    CodexComputerUseError,
    CodexComputerUsePaths,
)
from free_claude_code.runtime.codex_computer_use_helper import (
    CODEX_COMPUTER_USE_HELPER_ID,
    MUTATING_COMPUTER_USE_METHODS,
    READ_ONLY_COMPUTER_USE_METHODS,
    CodexComputerUseHelperAdapter,
)


def _paths() -> CodexComputerUsePaths:
    return CodexComputerUsePaths(
        codex=Path("/signed/codex"),
        app=Path("/signed/Codex Computer Use.app"),
        client=Path("/signed/SkyComputerUseClient"),
    )


def test_approved_helper_declares_native_capabilities_and_side_effects() -> None:
    adapter = CodexComputerUseHelperAdapter(paths=_paths())
    helper = adapter.approved_helper()

    assert helper.helper_id == CODEX_COMPUTER_USE_HELPER_ID
    assert helper.local is True
    assert helper.billable is False
    assert helper.capabilities == frozenset(
        {
            Capability.SEMANTIC_MACOS_CONTROL,
            Capability.PIXEL_COMPUTER_USE,
            Capability.SCREENSHOT_VISION,
        }
    )
    assert helper.mutating_operations == MUTATING_COMPUTER_USE_METHODS
    assert READ_ONLY_COMPUTER_USE_METHODS.isdisjoint(helper.mutating_operations)


def test_adapter_reuses_warm_broker() -> None:
    adapter = CodexComputerUseHelperAdapter(paths=_paths())
    broker = MagicMock()
    broker.started = True
    broker.call.return_value = {"content": [{"type": "text", "text": "ok"}]}
    adapter._broker = broker

    result = adapter.execute("list_apps", {}, threading.Event())

    assert result["content"][0]["text"] == "ok"
    broker.call.assert_called_once_with("list_apps", {})


def test_adapter_rejects_cancellation_before_dispatch() -> None:
    adapter = CodexComputerUseHelperAdapter(paths=_paths())
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(CodexComputerUseError, match="cancelled before dispatch"):
        adapter.execute("list_apps", {}, cancel)


def test_adapter_rejects_unknown_operation_before_broker_start() -> None:
    adapter = CodexComputerUseHelperAdapter(paths=_paths())

    with pytest.raises(CodexComputerUseError, match="unsupported"):
        adapter.execute("shell", {}, threading.Event())


def test_close_drops_owned_broker() -> None:
    adapter = CodexComputerUseHelperAdapter(paths=_paths())
    broker = MagicMock()
    broker.started = True
    adapter._broker = broker

    adapter.close()

    broker.close.assert_called_once_with()
    assert adapter._broker is None
