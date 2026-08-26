import pytest

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityHelper,
    CapabilityRouter,
    CapabilityRoutingMode,
    CapabilityRoutingPolicy,
    RequiredCapabilitySet,
)
from free_claude_code.application.fallback_policy import (
    ControllerFallbackPolicy,
    ControllerTarget,
    FallbackAttemptState,
    RecoveryKind,
    evaluate_controller_fallback,
    same_controller_retry_decision,
    select_controller_fallback,
)
from free_claude_code.core.failures import ExecutionFailure, FailureKind


_TEXT = frozenset({Capability.TEXT_INPUT, Capability.TEXT_OUTPUT})
_VISION = _TEXT | {Capability.VISION_INPUT}
_REQUIRED_TEXT = RequiredCapabilitySet(_TEXT)
_REQUIRED_VISION = RequiredCapabilitySet(_VISION)


def _target(
    model_ref: str,
    *,
    provider: str = "opencode_go",
    subscription: str = "opencode_go",
    protocol: str = "openai_responses",
    context: int = 256_000,
    capabilities: frozenset[Capability] = _TEXT,
) -> ControllerTarget:
    return ControllerTarget(
        provider_family=provider,
        model_ref=model_ref,
        subscription_scope=subscription,
        protocol_family=protocol,
        context_window_tokens=context,
        capabilities=capabilities,
    )


def _failure(
    kind: FailureKind = FailureKind.RATE_LIMIT,
    *,
    retryable: bool = True,
) -> ExecutionFailure:
    return ExecutionFailure(
        kind=kind,
        status_code=429 if kind is FailureKind.RATE_LIMIT else 400,
        message="synthetic upstream failure",
        retryable=retryable,
    )


def test_default_policy_produces_zero_controller_failover() -> None:
    source = _target("opencode_go/muse")
    target = _target("opencode_go/muse-backup")

    decision = evaluate_controller_fallback(
        source,
        target,
        _failure(),
        _REQUIRED_TEXT,
        FallbackAttemptState(),
        ControllerFallbackPolicy(),
    )

    assert decision.allowed is False
    assert decision.kind is RecoveryKind.FAIL
    assert decision.reason == "controller failover is disabled"


def test_retry_helper_and_controller_fallback_are_distinct_paths() -> None:
    source = _target("opencode_go/muse")
    failure = _failure()

    retry = same_controller_retry_decision(
        source,
        failure,
        FallbackAttemptState(),
    )
    assert retry.kind is RecoveryKind.SAME_CONTROLLER_RETRY
    assert retry.allowed is True

    helper = CapabilityHelper(
        helper_id="vision-local",
        provider_family="local",
        model_ref="local-tool",
        capabilities=frozenset({Capability.VISION_INPUT}),
        local=True,
        billable=False,
    )
    helper_plan = CapabilityRouter(
        CapabilityRoutingPolicy(
            mode=CapabilityRoutingMode.SMART_LOCAL,
            allowed_helpers=frozenset({"vision-local"}),
        )
    ).plan(
        _REQUIRED_VISION,
        controller_provider=source.provider_family,
        controller_model=source.model_ref,
        supported_capabilities=_TEXT,
        known_capabilities=_VISION,
        helpers=(helper,),
    )
    assert helper_plan.decision == "helpers"
    assert helper_plan.controller_failover is False

    fallback = evaluate_controller_fallback(
        source,
        _target("opencode_go/muse-backup", capabilities=_VISION),
        failure,
        _REQUIRED_VISION,
        FallbackAttemptState(),
        ControllerFallbackPolicy(
            allowed_model_refs=("opencode_go/muse-backup",),
        ),
    )
    assert fallback.kind is RecoveryKind.CONTROLLER_FALLBACK
    assert fallback.allowed is True


def test_post_commit_retry_and_controller_fallback_are_both_blocked() -> None:
    source = _target("opencode_go/muse")
    target = _target("opencode_go/muse-backup")
    state = FallbackAttemptState(committed_tool_execution=True)

    retry = same_controller_retry_decision(source, _failure(), state)
    fallback = evaluate_controller_fallback(
        source,
        target,
        _failure(),
        _REQUIRED_TEXT,
        state,
        ControllerFallbackPolicy(
            allowed_model_refs=(target.model_ref,),
        ),
    )

    assert retry.allowed is False
    assert fallback.allowed is False
    assert "committed" in fallback.reason


def test_fallback_requires_same_subscription_by_default() -> None:
    source = _target("opencode_go/muse")
    target = _target(
        "openai/gpt",
        provider="openai",
        subscription="chatgpt",
    )

    decision = evaluate_controller_fallback(
        source,
        target,
        _failure(),
        _REQUIRED_TEXT,
        FallbackAttemptState(),
        ControllerFallbackPolicy(allowed_model_refs=(target.model_ref,)),
    )

    assert decision.allowed is False
    assert "subscription" in decision.reason


def test_fallback_requires_target_capabilities_and_context_capacity() -> None:
    source = _target("opencode_go/muse")
    target = _target(
        "opencode_go/text-only",
        context=128_000,
        capabilities=_TEXT,
    )
    policy = ControllerFallbackPolicy(allowed_model_refs=(target.model_ref,))

    missing_vision = evaluate_controller_fallback(
        source,
        target,
        _failure(),
        _REQUIRED_VISION,
        FallbackAttemptState(request_context_tokens=64_000),
        policy,
    )
    too_large = evaluate_controller_fallback(
        source,
        target,
        _failure(),
        _REQUIRED_TEXT,
        FallbackAttemptState(request_context_tokens=200_000),
        policy,
    )

    assert missing_vision.allowed is False
    assert "vision_input" in missing_vision.reason
    assert too_large.allowed is False
    assert "context window" in too_large.reason


def test_context_window_failure_can_use_explicit_larger_same_subscription_target() -> None:
    source = _target("opencode_go/muse-128k", context=128_000)
    target = _target("opencode_go/muse-256k", context=256_000)
    failure = _failure(FailureKind.CONTEXT_WINDOW_EXCEEDED, retryable=False)

    decision = evaluate_controller_fallback(
        source,
        target,
        failure,
        _REQUIRED_TEXT,
        FallbackAttemptState(request_context_tokens=200_000),
        ControllerFallbackPolicy(allowed_model_refs=(target.model_ref,)),
    )

    assert decision.allowed is True
    assert decision.kind is RecoveryKind.CONTROLLER_FALLBACK


def test_nonretryable_auth_failure_never_becomes_controller_fallback() -> None:
    source = _target("opencode_go/muse")
    target = _target("opencode_go/muse-backup")

    decision = evaluate_controller_fallback(
        source,
        target,
        _failure(FailureKind.AUTHENTICATION, retryable=False),
        _REQUIRED_TEXT,
        FallbackAttemptState(),
        ControllerFallbackPolicy(allowed_model_refs=(target.model_ref,)),
    )

    assert decision.allowed is False
    assert "not eligible" in decision.reason


def test_any_target_switch_requires_canonical_request_rebuild() -> None:
    source = _target("opencode_go/muse")
    target = _target("opencode_go/muse-backup")

    decision = evaluate_controller_fallback(
        source,
        target,
        _failure(),
        _REQUIRED_TEXT,
        FallbackAttemptState(canonical_request_available=False),
        ControllerFallbackPolicy(allowed_model_refs=(target.model_ref,)),
    )

    assert decision.allowed is False
    assert "canonical request" in decision.reason


def test_cross_protocol_fallback_needs_explicit_policy_and_canonical_retranslation() -> None:
    source = _target("opencode_go/muse", protocol="openai_responses")
    target = _target("opencode_go/chat", protocol="openai_chat")

    disabled = evaluate_controller_fallback(
        source,
        target,
        _failure(),
        _REQUIRED_TEXT,
        FallbackAttemptState(),
        ControllerFallbackPolicy(allowed_model_refs=(target.model_ref,)),
    )
    enabled = evaluate_controller_fallback(
        source,
        target,
        _failure(),
        _REQUIRED_TEXT,
        FallbackAttemptState(canonical_request_available=True),
        ControllerFallbackPolicy(
            allowed_model_refs=(target.model_ref,),
            allow_cross_protocol=True,
        ),
    )

    assert disabled.allowed is False
    assert "cross-protocol" in disabled.reason
    assert enabled.allowed is True


def test_ordered_allowlist_skips_incompatible_target_and_receipts_final_choice() -> None:
    source = _target("opencode_go/muse", capabilities=_VISION)
    first = _target("opencode_go/text-only", capabilities=_TEXT)
    second = _target("opencode_go/vision-backup", capabilities=_VISION)
    policy = ControllerFallbackPolicy(
        allowed_model_refs=(first.model_ref, second.model_ref),
    )

    plan = select_controller_fallback(
        source,
        (second, first),
        _failure(),
        _REQUIRED_VISION,
        FallbackAttemptState(attempted_model_refs=(source.model_ref,)),
        policy,
    )

    assert plan.selected == second
    assert [decision.target_model for decision in plan.decisions] == [
        first.model_ref,
        second.model_ref,
    ]
    assert plan.decisions[0].allowed is False
    assert plan.decisions[1].allowed is True
    receipt = plan.as_receipt()
    assert receipt["selected_provider"] == "opencode_go"
    assert receipt["selected_model"] == second.model_ref
    assert receipt["decisions"][0]["reason"].startswith("target lacks")


def test_policy_rejects_duplicate_or_empty_fallback_refs() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        ControllerFallbackPolicy(allowed_model_refs=("",))
    with pytest.raises(ValueError, match="unique"):
        ControllerFallbackPolicy(allowed_model_refs=("a", "a"))
