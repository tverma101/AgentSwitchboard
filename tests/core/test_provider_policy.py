import pytest

from free_claude_code.core.provider_policy import (
    ProviderEgressGuard,
    ProviderPolicy,
    ProviderPolicyError,
)


def test_strict_policy_blocks_forbidden_provider_before_network() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    with pytest.raises(ProviderPolicyError, match="before network I/O"):
        guard.authorize("anthropic")

    assert guard.receipt()["counts"] == {}


def test_strict_policy_allows_primary_and_local_tool() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    guard.authorize("opencode_go")
    guard.authorize("computer", category="local_tool")

    assert guard.receipt()["counts"] == {"local": 1, "opencode_go": 1}


def test_localhost_model_url_is_not_treated_as_a_local_tool() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    with pytest.raises(ProviderPolicyError):
        guard.authorize_url("http://localhost:9222/json", category="model")


def test_configured_provider_family_can_use_an_explicit_proxy_host() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    guard.authorize_url(
        "https://proxy.example.test/v1",
        provider_family="opencode_go",
    )
    assert guard.receipt()["counts"] == {"opencode_go": 1}


def test_strict_policy_cannot_enable_paid_fallback() -> None:
    with pytest.raises(ValueError, match="paid fallback"):
        ProviderPolicy("opencode_go", "model", paid_fallback=True)
