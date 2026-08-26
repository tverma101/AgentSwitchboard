"""Fail-closed controller fallback policy separate from retries and helpers."""

from dataclasses import dataclass
from enum import StrEnum

from free_claude_code.application.capabilities import Capability, RequiredCapabilitySet
from free_claude_code.core.failures import ExecutionFailure, FailureKind


class RecoveryKind(StrEnum):
    """Mutually exclusive recovery paths after one controller attempt."""

    FAIL = "fail"
    SAME_CONTROLLER_RETRY = "same_controller_retry"
    CONTROLLER_FALLBACK = "controller_fallback"


@dataclass(frozen=True, slots=True)
class ControllerTarget:
    """Static controller metadata resolved before request execution."""

    provider_family: str
    model_ref: str
    subscription_scope: str
    protocol_family: str
    context_window_tokens: int
    capabilities: frozenset[Capability]

    def __post_init__(self) -> None:
        if not self.provider_family.strip():
            raise ValueError("provider_family is required")
        if not self.model_ref.strip():
            raise ValueError("model_ref is required")
        if not self.subscription_scope.strip():
            raise ValueError("subscription_scope is required")
        if not self.protocol_family.strip():
            raise ValueError("protocol_family is required")
        if self.context_window_tokens <= 0:
            raise ValueError("context_window_tokens must be positive")


@dataclass(frozen=True, slots=True)
class FallbackAttemptState:
    """Request state that determines whether replay remains safe."""

    attempted_model_refs: tuple[str, ...] = ()
    committed_output: bool = False
    committed_tool_execution: bool = False
    canonical_request_available: bool = True
    request_context_tokens: int = 0

    def __post_init__(self) -> None:
        if self.request_context_tokens < 0:
            raise ValueError("request_context_tokens cannot be negative")

    @property
    def committed(self) -> bool:
        return self.committed_output or self.committed_tool_execution


@dataclass(frozen=True, slots=True)
class ControllerFallbackPolicy:
    """Explicit ordered allowlist for controller replacement.

    An empty target list is the production default and means zero controller
    failover. Capability helpers are intentionally not represented here.
    """

    allowed_model_refs: tuple[str, ...] = ()
    same_subscription_only: bool = True
    allow_cross_protocol: bool = False
    allow_context_window_fallback: bool = True

    def __post_init__(self) -> None:
        if any(not model_ref.strip() for model_ref in self.allowed_model_refs):
            raise ValueError("fallback model refs cannot be empty")
        if len(set(self.allowed_model_refs)) != len(self.allowed_model_refs):
            raise ValueError("fallback model refs must be unique")

    @property
    def enabled(self) -> bool:
        return bool(self.allowed_model_refs)


@dataclass(frozen=True, slots=True)
class ControllerFallbackDecision:
    """One content-free eligibility decision for a controller target."""

    kind: RecoveryKind
    allowed: bool
    reason: str
    source_provider: str
    source_model: str
    target_provider: str | None
    target_model: str | None
    failure_kind: FailureKind

    def as_receipt(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "allowed": self.allowed,
            "reason": self.reason,
            "source_provider": self.source_provider,
            "source_model": self.source_model,
            "target_provider": self.target_provider,
            "target_model": self.target_model,
            "failure_kind": self.failure_kind.value,
        }


@dataclass(frozen=True, slots=True)
class ControllerFallbackPlan:
    """Ordered fallback selection and all target decisions considered."""

    selected: ControllerTarget | None
    decisions: tuple[ControllerFallbackDecision, ...]

    def as_receipt(self) -> dict[str, object]:
        return {
            "selected_provider": (
                self.selected.provider_family if self.selected is not None else None
            ),
            "selected_model": self.selected.model_ref if self.selected is not None else None,
            "decisions": [decision.as_receipt() for decision in self.decisions],
        }


def same_controller_retry_decision(
    source: ControllerTarget,
    failure: ExecutionFailure,
    state: FallbackAttemptState,
) -> ControllerFallbackDecision:
    """Classify a same-controller retry without consulting fallback policy."""

    if state.committed:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "request already committed output or tool execution",
            source,
            None,
            failure,
        )
    if not failure.retryable:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "failure is not retryable on the same controller",
            source,
            None,
            failure,
        )
    return _decision(
        RecoveryKind.SAME_CONTROLLER_RETRY,
        True,
        "retryable failure before commit",
        source,
        source,
        failure,
    )


def evaluate_controller_fallback(
    source: ControllerTarget,
    target: ControllerTarget,
    failure: ExecutionFailure,
    required: RequiredCapabilitySet,
    state: FallbackAttemptState,
    policy: ControllerFallbackPolicy,
) -> ControllerFallbackDecision:
    """Evaluate one explicitly configured controller replacement target."""

    if target.model_ref == source.model_ref:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "same controller belongs to retry policy, not fallback policy",
            source,
            target,
            failure,
        )
    if state.committed:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "request already committed output or tool execution",
            source,
            target,
            failure,
        )
    if not policy.enabled:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "controller failover is disabled",
            source,
            target,
            failure,
        )
    if target.model_ref not in policy.allowed_model_refs:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "target is not in the explicit fallback allowlist",
            source,
            target,
            failure,
        )
    if target.model_ref in state.attempted_model_refs:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "target was already attempted",
            source,
            target,
            failure,
        )
    if not state.canonical_request_available:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "controller fallback requires canonical request rebuild",
            source,
            target,
            failure,
        )
    if (
        policy.same_subscription_only
        and target.subscription_scope != source.subscription_scope
    ):
        return _decision(
            RecoveryKind.FAIL,
            False,
            "target is outside the controller subscription scope",
            source,
            target,
            failure,
        )
    if target.protocol_family != source.protocol_family and not policy.allow_cross_protocol:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "cross-protocol controller fallback is disabled",
            source,
            target,
            failure,
        )

    missing = required.capabilities - target.capabilities
    if missing:
        names = ", ".join(sorted(capability.value for capability in missing))
        return _decision(
            RecoveryKind.FAIL,
            False,
            f"target lacks required capabilities: {names}",
            source,
            target,
            failure,
        )
    if state.request_context_tokens > target.context_window_tokens:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "request exceeds target context window",
            source,
            target,
            failure,
        )

    if failure.kind is FailureKind.CONTEXT_WINDOW_EXCEEDED:
        if not policy.allow_context_window_fallback:
            return _decision(
                RecoveryKind.FAIL,
                False,
                "context-window fallback is disabled",
                source,
                target,
                failure,
            )
        if target.context_window_tokens <= source.context_window_tokens:
            return _decision(
                RecoveryKind.FAIL,
                False,
                "context fallback target is not larger than the source",
                source,
                target,
                failure,
            )
    elif not failure.retryable:
        return _decision(
            RecoveryKind.FAIL,
            False,
            "failure class is not eligible for controller fallback",
            source,
            target,
            failure,
        )

    return _decision(
        RecoveryKind.CONTROLLER_FALLBACK,
        True,
        "explicit compatible fallback target before commit",
        source,
        target,
        failure,
    )


def select_controller_fallback(
    source: ControllerTarget,
    targets: tuple[ControllerTarget, ...],
    failure: ExecutionFailure,
    required: RequiredCapabilitySet,
    state: FallbackAttemptState,
    policy: ControllerFallbackPolicy,
) -> ControllerFallbackPlan:
    """Select the first eligible target in the policy's declared order."""

    by_ref = {target.model_ref: target for target in targets}
    decisions: list[ControllerFallbackDecision] = []
    for model_ref in policy.allowed_model_refs:
        target = by_ref.get(model_ref)
        if target is None:
            decisions.append(
                ControllerFallbackDecision(
                    kind=RecoveryKind.FAIL,
                    allowed=False,
                    reason="allowlisted target metadata is unavailable",
                    source_provider=source.provider_family,
                    source_model=source.model_ref,
                    target_provider=None,
                    target_model=model_ref,
                    failure_kind=failure.kind,
                )
            )
            continue
        decision = evaluate_controller_fallback(
            source,
            target,
            failure,
            required,
            state,
            policy,
        )
        decisions.append(decision)
        if decision.allowed:
            return ControllerFallbackPlan(
                selected=target,
                decisions=tuple(decisions),
            )
    return ControllerFallbackPlan(selected=None, decisions=tuple(decisions))


def _decision(
    kind: RecoveryKind,
    allowed: bool,
    reason: str,
    source: ControllerTarget,
    target: ControllerTarget | None,
    failure: ExecutionFailure,
) -> ControllerFallbackDecision:
    return ControllerFallbackDecision(
        kind=kind,
        allowed=allowed,
        reason=reason,
        source_provider=source.provider_family,
        source_model=source.model_ref,
        target_provider=target.provider_family if target is not None else None,
        target_model=target.model_ref if target is not None else None,
        failure_kind=failure.kind,
    )


__all__ = [
    "ControllerFallbackDecision",
    "ControllerFallbackPlan",
    "ControllerFallbackPolicy",
    "ControllerTarget",
    "FallbackAttemptState",
    "RecoveryKind",
    "evaluate_controller_fallback",
    "same_controller_retry_decision",
    "select_controller_fallback",
]
