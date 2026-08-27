"""Tests for bounded explicitly approved helper execution."""

import json
import threading

import pytest

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityRouter,
    CapabilityRoutingMode,
    CapabilityRoutingPolicy,
    RequiredCapabilitySet,
)
from free_claude_code.application.helpers import (
    ApprovedHelper,
    ApprovedHelperExecutor,
    ApprovedHelperRegistry,
    HelperIndeterminateError,
    HelperOutputError,
    HelperTimeoutError,
)
from free_claude_code.core.provider_policy import (
    ProviderEgressGuard,
    ProviderPolicy,
    ProviderPolicyError,
)


def _local_guard() -> ProviderEgressGuard:
    return ProviderEgressGuard(
        ProviderPolicy(
            primary_provider="opencode_go",
            primary_model="muse",
            allowed_local_tools=frozenset({"computer", "browser"}),
        )
    )


def _computer_helper(execute, *, max_output_bytes: int = 65536) -> ApprovedHelper:
    return ApprovedHelper(
        helper_id="codex-computer-use",
        provider_family="computer",
        capabilities=frozenset(
            {
                Capability.SEMANTIC_MACOS_CONTROL,
                Capability.PIXEL_COMPUTER_USE,
            }
        ),
        execute=execute,
        max_output_bytes=max_output_bytes,
    )


def test_registry_is_explicit_deterministic_and_freezable() -> None:
    registry = ApprovedHelperRegistry()
    registry.register(_computer_helper(lambda operation, arguments, cancel: {}))

    metadata = registry.router_helpers()
    assert [helper.helper_id for helper in metadata] == ["codex-computer-use"]
    assert metadata[0].local is True
    assert registry.receipt()[0]["capabilities"] == [
        "pixel_computer_use",
        "semantic_macos_control",
    ]

    registry.freeze()
    assert registry.frozen is True
    with pytest.raises(RuntimeError, match="frozen"):
        registry.register(
            ApprovedHelper(
                helper_id="other",
                provider_family="browser",
                capabilities=frozenset({Capability.SEMANTIC_BROWSER_CONTROL}),
                execute=lambda operation, arguments, cancel: {},
            )
        )


def test_existing_capability_router_selects_registered_helper() -> None:
    registry = ApprovedHelperRegistry()
    registry.register(
        _computer_helper(lambda operation, arguments, cancel: {"ok": True})
    )
    registry.freeze()

    router = CapabilityRouter(
        CapabilityRoutingPolicy(
            mode=CapabilityRoutingMode.SMART_LOCAL,
            allowed_helpers=frozenset({"codex-computer-use"}),
        )
    )
    required = RequiredCapabilitySet(
        capabilities=frozenset(
            {
                Capability.TEXT_INPUT,
                Capability.TEXT_OUTPUT,
                Capability.SEMANTIC_MACOS_CONTROL,
            }
        )
    )
    plan = router.plan(
        required,
        controller_provider="opencode_go",
        controller_model="muse",
        known_capabilities=frozenset({Capability.SEMANTIC_MACOS_CONTROL}),
        helpers=registry.router_helpers(),
    )

    assert plan.decision == "helpers"
    assert [helper.helper_id for helper in plan.helpers] == ["codex-computer-use"]

    result = ApprovedHelperExecutor(registry, _local_guard()).execute_planned(
        plan,
        helper_id="codex-computer-use",
        operation="list_apps",
        arguments={},
    )
    assert result.output == {"ok": True}
    assert result.receipt.status.value == "success"
    assert result.receipt.attempts == 1


def test_execute_planned_rejects_helper_not_selected_by_router() -> None:
    registry = ApprovedHelperRegistry()
    registry.register(
        _computer_helper(lambda operation, arguments, cancel: {"ok": True})
    )
    registry.freeze()
    router = CapabilityRouter()
    plan = router.plan(
        RequiredCapabilitySet(
            capabilities=frozenset({Capability.TEXT_INPUT, Capability.TEXT_OUTPUT})
        ),
        controller_provider="opencode_go",
        controller_model="muse",
    )

    with pytest.raises(PermissionError, match="not selected"):
        ApprovedHelperExecutor(registry, _local_guard()).execute_planned(
            plan,
            helper_id="codex-computer-use",
            operation="list_apps",
            arguments={},
        )


def test_provider_guard_blocks_forbidden_helper_before_execution() -> None:
    executed = False

    def run(operation, arguments, cancel):
        nonlocal executed
        executed = True
        return {"ok": True}

    registry = ApprovedHelperRegistry()
    registry.register(
        ApprovedHelper(
            helper_id="paid-codex",
            provider_family="openai",
            capabilities=frozenset({Capability.VISION_INPUT}),
            execute=run,
            local=False,
            billable=True,
        )
    )
    registry.freeze()

    with pytest.raises(ProviderPolicyError, match="blocked before network I/O"):
        ApprovedHelperExecutor(registry, _local_guard()).execute(
            helper_id="paid-codex",
            operation="inspect",
            arguments={"secret": "never-sent"},
        )
    assert executed is False


def test_timeout_sets_cancel_event_and_returns_control() -> None:
    saw_cancel = threading.Event()

    def run(operation, arguments, cancel):
        cancel.wait(timeout=1)
        if cancel.is_set():
            saw_cancel.set()
        return {"cancelled": cancel.is_set()}

    registry = ApprovedHelperRegistry()
    registry.register(_computer_helper(run))
    registry.freeze()
    executor = ApprovedHelperExecutor(
        registry,
        _local_guard(),
        default_timeout_seconds=0.01,
        cancellation_grace_seconds=0.2,
    )

    with pytest.raises(HelperTimeoutError) as captured:
        executor.execute(
            helper_id="codex-computer-use",
            operation="list_apps",
            arguments={},
        )

    assert saw_cancel.wait(timeout=0.2)
    assert captured.value.receipt.status.value == "timed_out"
    assert captured.value.receipt.attempts == 1


def test_unproven_cancellation_is_indeterminate_not_retried() -> None:
    release = threading.Event()

    def run(operation, arguments, cancel):
        release.wait(timeout=1)
        return {"late": True}

    registry = ApprovedHelperRegistry()
    registry.register(_computer_helper(run))
    registry.freeze()
    executor = ApprovedHelperExecutor(
        registry,
        _local_guard(),
        default_timeout_seconds=0.01,
        cancellation_grace_seconds=0.01,
    )

    try:
        with pytest.raises(HelperIndeterminateError) as captured:
            executor.execute(
                helper_id="codex-computer-use",
                operation="click",
                arguments={"app": "TextEdit"},
            )
        assert captured.value.receipt.status.value == "indeterminate"
        assert captured.value.receipt.attempts == 1
    finally:
        release.set()


def test_output_must_be_json_and_within_bound() -> None:
    registry = ApprovedHelperRegistry()
    registry.register(
        _computer_helper(
            lambda operation, arguments, cancel: {"text": "x" * 100},
            max_output_bytes=32,
        )
    )
    registry.freeze()

    with pytest.raises(HelperOutputError) as captured:
        ApprovedHelperExecutor(registry, _local_guard()).execute(
            helper_id="codex-computer-use",
            operation="get_app_state",
            arguments={},
        )
    assert captured.value.receipt.status.value == "output_rejected"
    assert captured.value.receipt.output_bytes is not None


def test_receipt_contains_no_arguments_or_output_content() -> None:
    registry = ApprovedHelperRegistry()
    registry.register(
        _computer_helper(
            lambda operation, arguments, cancel: {
                "summary": "safe-result",
            }
        )
    )
    registry.freeze()

    result = ApprovedHelperExecutor(registry, _local_guard()).execute(
        helper_id="codex-computer-use",
        operation="get_app_state",
        arguments={"secret": "do-not-record"},
    )

    encoded = json.dumps(result.receipt.as_dict(), sort_keys=True)
    assert "do-not-record" not in encoded
    assert "safe-result" not in encoded
    assert result.receipt.failure_owner is None
