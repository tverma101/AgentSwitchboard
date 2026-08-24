from unittest.mock import patch

import pytest

from free_claude_code.core.provider_policy import (
    ProviderEgressGuard,
    ProviderPolicy,
    ProviderPolicyError,
    ProviderPolicyMode,
)


def test_strict_policy_blocks_forbidden_provider_before_network() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    with (
        patch("free_claude_code.core.provider_policy.trace_event") as trace,
        pytest.raises(ProviderPolicyError, match="before network I/O"),
    ):
        guard.authorize("anthropic")

    assert guard.receipt()["counts"] == {}
    trace.assert_called_once_with(
        stage="provider_policy",
        event="provider.egress.decision",
        source="provider_policy",
        provider_family="anthropic",
        destination_host=None,
        category="model",
        decision="blocked",
        policy_mode="strict",
        primary_provider="opencode_go",
        paid_fallback=False,
    )


def test_strict_policy_allows_primary_and_local_tool() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    guard.authorize("opencode_go")
    guard.authorize("computer", category="local_tool")

    assert guard.receipt()["counts"] == {"local": 1, "opencode_go": 1}


def test_localhost_model_url_is_not_treated_as_a_local_tool() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    with pytest.raises(ProviderPolicyError):
        guard.authorize_url("http://localhost:9222/json", category="model")


def test_primary_provider_may_use_an_explicit_local_fixture_endpoint() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    guard.authorize_url(
        "http://127.0.0.1:9222/v1",
        category="model",
        provider_family="opencode_go",
    )

    assert guard.receipt()["counts"] == {"opencode_go": 1}


def test_configured_provider_family_can_use_an_explicit_proxy_host() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    with patch("free_claude_code.core.provider_policy.trace_event") as trace:
        guard.authorize_url(
            "https://proxy.example.test/v1",
            provider_family="opencode_go",
        )
    assert guard.receipt()["counts"] == {"opencode_go": 1}
    trace.assert_called_once_with(
        stage="provider_policy",
        event="provider.egress.decision",
        source="provider_policy",
        provider_family="opencode_go",
        destination_host="proxy.example.test",
        category="model",
        decision="allowed",
        policy_mode="strict",
        primary_provider="opencode_go",
        paid_fallback=False,
    )


def test_diagnostic_policy_records_blocked_destinations_without_authorizing_them() -> (
    None
):
    guard = ProviderEgressGuard(
        ProviderPolicy("opencode_go", "model", mode=ProviderPolicyMode.DIAGNOSTIC)
    )

    assert guard.authorize("anthropic") is False

    receipt = guard.receipt()
    assert receipt["counts"] == {}
    assert receipt["blocked_counts"] == {"anthropic": 1}


def test_strict_policy_cannot_enable_paid_fallback() -> None:
    with pytest.raises(ValueError, match="paid fallback"):
        ProviderPolicy("opencode_go", "model", paid_fallback=True)
