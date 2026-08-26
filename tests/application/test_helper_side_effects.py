"""Side-effect and explicit-timeout regressions for approved helpers."""

import threading

import pytest

from free_claude_code.application.capabilities import Capability
from free_claude_code.application.helpers import (
    ApprovedHelper,
    ApprovedHelperExecutor,
    ApprovedHelperRegistry,
    HelperIndeterminateError,
)
from free_claude_code.core.provider_policy import ProviderEgressGuard, ProviderPolicy


def _guard() -> ProviderEgressGuard:
    return ProviderEgressGuard(
        ProviderPolicy(
            primary_provider="opencode_go",
            primary_model="muse",
            allowed_local_tools=frozenset({"computer"}),
        )
    )


def test_mutating_timeout_stays_indeterminate_even_when_cancel_finishes() -> None:
    saw_cancel = threading.Event()

    def execute(operation, arguments, cancel):
        cancel.wait(timeout=1)
        saw_cancel.set()
        return {"cancelled": True}

    registry = ApprovedHelperRegistry()
    registry.register(
        ApprovedHelper(
            helper_id="computer",
            provider_family="computer",
            capabilities=frozenset({Capability.SEMANTIC_MACOS_CONTROL}),
            execute=execute,
            mutating_operations=frozenset({"click"}),
        )
    )
    registry.freeze()
    executor = ApprovedHelperExecutor(
        registry,
        _guard(),
        default_timeout_seconds=0.01,
        cancellation_grace_seconds=0.2,
    )

    with pytest.raises(HelperIndeterminateError) as captured:
        executor.execute(
            helper_id="computer",
            operation="click",
            arguments={"app": "TextEdit"},
        )

    assert saw_cancel.wait(timeout=0.2)
    assert captured.value.receipt.status.value == "indeterminate"
    assert captured.value.receipt.attempts == 1


def test_explicit_zero_timeout_is_rejected() -> None:
    registry = ApprovedHelperRegistry()
    registry.register(
        ApprovedHelper(
            helper_id="computer",
            provider_family="computer",
            capabilities=frozenset({Capability.SEMANTIC_MACOS_CONTROL}),
            execute=lambda operation, arguments, cancel: {"ok": True},
        )
    )
    registry.freeze()

    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        ApprovedHelperExecutor(registry, _guard()).execute(
            helper_id="computer",
            operation="list_apps",
            arguments={},
            timeout_seconds=0,
        )
