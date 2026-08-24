from dataclasses import FrozenInstanceError
from typing import cast
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
    trace.assert_called_once()
    payload = trace.call_args.kwargs
    assert payload["provider_family"] == "anthropic"
    assert payload["decision"] == "blocked"
    assert payload["reason"] == "forbidden_provider_family"
    assert payload["fault_domain"] == "harness_bridge"
    assert payload["evidence_codes"] == ["provider_policy_blocked"]


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
    trace.assert_called_once()
    payload = trace.call_args.kwargs
    assert payload["provider_family"] == "opencode_go"
    assert payload["destination_host"] == "proxy.example.test"
    assert payload["decision"] == "allowed"
    assert payload["reason"] is None


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


def test_session_policy_is_frozen_and_normalizes_safe_receipts() -> None:
    policy = ProviderPolicy("OpenCode_Go", "model")

    with pytest.raises(FrozenInstanceError):
        attribute_name = "primary_" + "provider"
        setattr(policy, attribute_name, "openai")

    receipt = policy.as_receipt()
    assert receipt["primary_provider"] == "opencode_go"
    assert receipt["session_id"] == "unbound"


def test_allow_listed_helper_requires_an_exact_explicit_model() -> None:
    guard = ProviderEgressGuard(
        ProviderPolicy(
            "opencode_go",
            "model",
            allowed_helpers=frozenset({"local_vision/vision-1"}),
            mode=ProviderPolicyMode.ALLOW_LISTED,
        )
    )

    guard.authorize(
        "local_vision",
        model="vision-1",
        category="helper",
        session_id="session-a",
    )
    with pytest.raises(ProviderPolicyError, match="helper"):
        guard.authorize(
            "local_vision",
            model="vision-2",
            category="helper",
            session_id="session-a",
        )

    assert guard.session_receipt("session-a")["counts"] == {"local_vision": 1}


def test_diagnostic_policy_records_a_would_be_fallback_without_fake_egress() -> None:
    guard = ProviderEgressGuard(
        ProviderPolicy(
            "opencode_go",
            "model",
            mode=ProviderPolicyMode.DIAGNOSTIC,
        )
    )
    fake_calls: list[str] = []

    if guard.authorize("anthropic", session_id="session-a"):
        fake_calls.append("anthropic")

    receipt = guard.session_receipt("session-a")
    assert fake_calls == []
    assert receipt["counts"] == {}
    assert receipt["blocked_counts"] == {"anthropic": 1}
    assert receipt["would_be_fallbacks"] == {"anthropic": 1}


def test_session_accounting_is_sanitized_and_keeps_local_and_forbidden_rows() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))
    session_id = "secret-session-id"

    guard.authorize(
        "opencode_go",
        model="model",
        session_id=session_id,
        request_id="req-1",
    )
    guard.authorize(
        "local",
        model="browser.list_tabs",
        category="local_tool",
        session_id=session_id,
    )
    guard.record_usage(
        "opencode_go",
        model="model",
        session_id=session_id,
        input_tokens=11,
        output_tokens=7,
        cache_read_tokens=3,
        cache_write_tokens=2,
        retry_count=1,
    )

    receipt = guard.session_receipt(session_id)
    session_label = cast(str, receipt["session_id"])
    accounting = cast(dict[str, dict[str, int]], receipt["accounting"])
    assert session_label.startswith("session_")
    assert session_id not in repr(receipt)
    assert receipt["counts"] == {"local": 1, "opencode_go": 1}
    assert accounting["opencode_go"] == {
        "request_count": 1,
        "model_requests": 1,
        "helper_requests": 0,
        "local_tool_actions": 0,
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_tokens": 3,
        "cache_write_tokens": 2,
        "image_bytes": 0,
        "retry_count": 1,
    }
    assert accounting["local"]["local_tool_actions"] == 1
    assert accounting["anthropic"]["request_count"] == 0


def test_known_forbidden_hosts_and_remote_local_tools_are_blocked_before_send() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))

    with pytest.raises(ProviderPolicyError):
        guard.authorize_url("https://api.anthropic.com/v1/messages")
    with pytest.raises(ProviderPolicyError):
        guard.authorize_url("https://remote.example.test/cdp", category="local_tool")
    with pytest.raises(ProviderPolicyError):
        guard.authorize_url(
            "https://remote.example.test/cdp",
            category="local_tool",
            provider_family="local",
        )
    with pytest.raises(ProviderPolicyError):
        guard.authorize_url(
            "https://api.openai.com/v1",
            provider_family="opencode_go",
        )
    with pytest.raises(ProviderPolicyError, match="credentials"):
        guard.authorize_url("https://user:password@api.opencode.ai/v1")
