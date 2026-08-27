"""Contract tests for one shared launch/session execution policy."""

import threading
from collections.abc import Mapping
from typing import Any

import pytest

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityRouter,
    CapabilityRoutingError,
    CapabilityRoutingMode,
    RequiredCapabilitySet,
)
from free_claude_code.application.helpers import ApprovedHelper, ApprovedHelperRegistry
from free_claude_code.application.session_policy import build_session_execution_policy
from free_claude_code.core.provider_policy import (
    ProviderPolicyError,
    ProviderPolicyMode,
)


def _helper(
    helper_id: str,
    *,
    provider_family: str = "computer",
    local: bool = True,
    billable: bool = False,
) -> ApprovedHelper:
    def execute(
        operation: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event,
    ) -> dict[str, object]:
        return {
            "operation": operation,
            "argument_count": len(arguments),
            "cancelled": cancel_event.is_set(),
        }

    return ApprovedHelper(
        helper_id=helper_id,
        provider_family=provider_family,
        capabilities=frozenset({Capability.PIXEL_COMPUTER_USE}),
        execute=execute,
        local=local,
        billable=billable,
    )


def _registry(*helpers: ApprovedHelper) -> ApprovedHelperRegistry:
    registry = ApprovedHelperRegistry()
    for helper in helpers:
        registry.register(helper)
    registry.freeze()
    return registry


def test_default_session_policy_has_zero_helper_escape() -> None:
    registry = _registry(_helper("codex-computer-use"))

    policy = build_session_execution_policy(
        "opencode_go/muse-spark-1.2-contributor",
        registry,
    )

    assert policy.allowed_helper_ids == frozenset()
    assert policy.provider_policy.mode is ProviderPolicyMode.STRICT
    assert policy.routing_policy.mode is CapabilityRoutingMode.STRICT
    assert policy.provider_policy.paid_fallback is False

    with pytest.raises(ProviderPolicyError):
        policy.egress_guard.authorize("openai")


def test_explicit_local_computer_helper_shares_one_guard_with_executor() -> None:
    registry = _registry(_helper("codex-computer-use"))
    policy = build_session_execution_policy(
        "opencode_go/muse-spark-1.2-contributor",
        registry,
        allowed_helper_ids={"codex-computer-use"},
        routing_mode=CapabilityRoutingMode.SMART_LOCAL,
    )
    executor = policy.helper_executor(registry)

    route = CapabilityRouter(policy.routing_policy).plan(
        RequiredCapabilitySet(frozenset({Capability.PIXEL_COMPUTER_USE})),
        controller_provider="opencode_go",
        controller_model="muse-spark-1.2-contributor",
        known_capabilities=frozenset({Capability.PIXEL_COMPUTER_USE}),
        helpers=registry.router_helpers(),
    )
    result = executor.execute_planned(
        route,
        helper_id="codex-computer-use",
        operation="list_apps",
        arguments={},
    )

    assert result.output["operation"] == "list_apps"
    receipt = policy.receipt()
    assert receipt["allowed_helpers"] == ["codex-computer-use"]
    egress = receipt["egress"]
    assert isinstance(egress, dict)
    counts = egress.get("counts")
    assert isinstance(counts, dict)
    assert counts == {"local": 1}
    assert "openai" not in counts


def test_helper_binary_or_credentials_do_not_authorize_unlisted_helper() -> None:
    registry = _registry(_helper("codex-computer-use"))
    policy = build_session_execution_policy(
        "opencode_go/muse-spark-1.2-contributor",
        registry,
    )

    route_router = CapabilityRouter(policy.routing_policy)
    with pytest.raises(CapabilityRoutingError, match="unavailable"):
        route_router.plan(
            RequiredCapabilitySet(frozenset({Capability.PIXEL_COMPUTER_USE})),
            controller_provider="opencode_go",
            controller_model="muse-spark-1.2-contributor",
            known_capabilities=frozenset({Capability.PIXEL_COMPUTER_USE}),
            helpers=registry.router_helpers(),
        )


def test_unregistered_helper_is_rejected_at_policy_construction() -> None:
    registry = _registry(_helper("codex-computer-use"))

    with pytest.raises(ValueError, match="unregistered helper"):
        build_session_execution_policy(
            "opencode_go/muse-spark-1.2-contributor",
            registry,
            allowed_helper_ids={"made-up-helper"},
            routing_mode=CapabilityRoutingMode.CUSTOM,
        )


def test_billable_helper_requires_explicit_paid_fallback_and_allowlisted_mode() -> None:
    registry = _registry(
        _helper(
            "codex-model",
            provider_family="openai",
            local=False,
            billable=True,
        )
    )

    with pytest.raises(ValueError, match="paid_fallback"):
        build_session_execution_policy(
            "opencode_go/muse-spark-1.2-contributor",
            registry,
            allowed_helper_ids={"codex-model"},
            provider_mode=ProviderPolicyMode.ALLOW_LISTED,
            routing_mode=CapabilityRoutingMode.CUSTOM,
        )

    policy = build_session_execution_policy(
        "opencode_go/muse-spark-1.2-contributor",
        registry,
        allowed_helper_ids={"codex-model"},
        provider_mode=ProviderPolicyMode.ALLOW_LISTED,
        routing_mode=CapabilityRoutingMode.CUSTOM,
        paid_fallback=True,
    )

    assert policy.egress_guard.authorize("openai", category="helper") is True
    assert policy.receipt()["paid_fallback"] is True


def test_remote_helper_cannot_hide_behind_non_allowlisted_provider_mode() -> None:
    registry = _registry(
        _helper(
            "remote-helper",
            provider_family="other-provider",
            local=False,
            billable=False,
        )
    )

    with pytest.raises(ValueError, match="allow-listed"):
        build_session_execution_policy(
            "opencode_go/muse-spark-1.2-contributor",
            registry,
            allowed_helper_ids={"remote-helper"},
            routing_mode=CapabilityRoutingMode.CUSTOM,
        )
