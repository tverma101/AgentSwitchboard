"""Metadata-only route explanations shared by Admin and the terminal CLI."""

from collections.abc import Sequence
from typing import Any

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityHelper,
    CapabilityRouter,
    CapabilityRoutingError,
    CapabilityRoutingMode,
    CapabilityRoutingPolicy,
    required_capabilities_for_messages,
)
from free_claude_code.application.model_metadata import (
    CapabilityEvidenceStatus,
    ProviderModelInfo,
    ReasoningCapabilityStatus,
)
from free_claude_code.application.ports import RequestRuntimePort
from free_claude_code.application.routing import ModelRouter
from free_claude_code.config.model_protocols import OPENCODE_GO_MODEL_PROTOCOLS
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.models import Message, MessagesRequest, Tool
from free_claude_code.core.provider_policy import ProviderPolicy

SYNTHETIC_REQUEST_SHAPES = frozenset(
    {
        "text",
        "tools",
        "parallel-tools",
        "vision",
        "image-tool-result",
        "reasoning",
        "structured",
        "browser",
        "macos",
        "screenshot",
    }
)

_BASELINE_CAPABILITIES = frozenset({Capability.TEXT_INPUT, Capability.TEXT_OUTPUT})


def parse_synthetic_shapes(value: str | Sequence[str]) -> tuple[str, ...]:
    """Normalize a comma-separated or already-split synthetic shape fixture."""

    parts = (
        value.split(",") if isinstance(value, str) else [str(part) for part in value]
    )
    shapes = tuple(dict.fromkeys(part.strip() for part in parts if part.strip()))
    unknown = sorted(set(shapes) - SYNTHETIC_REQUEST_SHAPES)
    if unknown:
        raise ValueError(f"unknown synthetic request shape(s): {', '.join(unknown)}")
    return shapes or ("text",)


def build_route_diagnostic(
    settings: Settings,
    *,
    runtime: RequestRuntimePort | None = None,
    model_info: ProviderModelInfo | None = None,
    model: str | None = None,
    shapes: str | Sequence[str] = ("text",),
    mode: CapabilityRoutingMode = CapabilityRoutingMode.STRICT,
    known_capabilities: frozenset[Capability] = frozenset(),
    supported_capabilities: frozenset[Capability] = frozenset(),
    helpers: tuple[CapabilityHelper, ...] = (),
    allowed_helpers: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Build one synthetic route explanation without provider I/O.

    ``runtime`` is read only: the diagnostic consults an already-populated model
    metadata cache and never acquires a provider generation or refreshes it.
    Explicit capability sets remain available to the CLI as diagnostic
    assertions; Admin uses the cached model evidence instead.
    """

    normalized_shapes = parse_synthetic_shapes(shapes)
    requested_model = model or settings.model
    request = _synthetic_request(requested_model, normalized_shapes)
    resolved = ModelRouter(settings).resolve(request.model)
    if model_info is None and runtime is not None:
        model_info = runtime.cached_model_info(
            resolved.provider_id, resolved.provider_model
        )

    required = required_capabilities_for_messages(request)
    rows, supported, known, evidence_summary = _effective_capability_evidence(
        required.capabilities,
        model_info=model_info,
        known_overrides=known_capabilities,
        supported_overrides=supported_capabilities,
    )
    policy = CapabilityRoutingPolicy(
        mode=mode,
        allowed_helpers=allowed_helpers,
    )
    router = CapabilityRouter(policy)
    try:
        plan = router.plan(
            required,
            controller_provider=resolved.provider_id,
            controller_model=resolved.provider_model,
            supported_capabilities=supported,
            known_capabilities=known,
            helpers=helpers,
        )
    except CapabilityRoutingError as exc:
        decision: dict[str, object] = {
            "controller_provider": resolved.provider_id,
            "controller_model": resolved.provider_model,
            "required": required.as_dict(),
            "mode": mode.value,
            "decision": "rejected",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    else:
        decision = plan.as_receipt()

    return {
        "diagnostic": "capability_route",
        "network": "none",
        "billable_requests": 0,
        "controller": {
            "requested_model": requested_model,
            "provider": resolved.provider_id,
            "model": resolved.provider_model,
            "model_ref": resolved.provider_model_ref,
            "protocol": _protocol_name(resolved.provider_id, resolved.provider_model),
            "virtual_context_window": resolved.virtual_context_window,
        },
        "request_shape": list(normalized_shapes),
        "required": required.as_dict(),
        "capability_evidence": rows,
        "effective_capabilities": evidence_summary,
        "policy": {
            "mode": mode.value,
            "controller_failover": False,
            "allowed_helpers": sorted(policy.allowed_helpers),
        },
        "provider_isolation": _provider_isolation_receipt(
            ProviderPolicy(
                primary_provider=resolved.provider_id,
                primary_model=resolved.provider_model,
            )
        ),
        "decision": decision,
    }


def _effective_capability_evidence(
    required: frozenset[Capability],
    *,
    model_info: ProviderModelInfo | None,
    known_overrides: frozenset[Capability],
    supported_overrides: frozenset[Capability],
) -> tuple[
    list[dict[str, str]],
    frozenset[Capability],
    frozenset[Capability],
    dict[str, object],
]:
    rows: list[dict[str, str]] = []
    supported: set[Capability] = set()
    known: set[Capability] = set()
    for capability in sorted(required, key=lambda item: item.value):
        status, source = _status_for_capability(
            capability,
            model_info=model_info,
            known_overrides=known_overrides,
            supported_overrides=supported_overrides,
        )
        state = status if status in {"supported", "unsupported"} else "unknown"
        if state == "supported":
            supported.add(capability)
            known.add(capability)
        elif state == "unsupported":
            known.add(capability)
        rows.append(
            {
                "capability": capability.value,
                "state": state,
                "evidence_status": status,
                "confidence": _confidence_for_status(status),
                "evidence_source": source,
            }
        )

    evidence = model_info.capability_evidence if model_info is not None else None
    evidence_source = evidence.evidence_source if evidence is not None else "unknown"
    if model_info is not None and evidence_source == "unknown":
        evidence_source = "model_metadata"
    return (
        rows,
        frozenset(supported),
        frozenset(known),
        {
            "evidence_source": evidence_source,
            "observed_at": evidence.observed_at if evidence is not None else None,
            "evidence_version": (
                evidence.evidence_version if evidence is not None else None
            ),
            "evidence_protocol": (
                evidence.evidence_protocol if evidence is not None else None
            ),
            "states": {row["capability"]: row["state"] for row in rows},
        },
    )


def _status_for_capability(
    capability: Capability,
    *,
    model_info: ProviderModelInfo | None,
    known_overrides: frozenset[Capability],
    supported_overrides: frozenset[Capability],
) -> tuple[str, str]:
    if capability in _BASELINE_CAPABILITIES:
        return "supported", "protocol-baseline"
    if capability in supported_overrides:
        return "supported", "cli-asserted"
    if capability in known_overrides:
        return "unsupported", "cli-asserted"
    if model_info is None:
        return "unknown", "unknown"

    evidence = model_info.capability_evidence
    status = evidence.status_for(capability.value)
    if status is not CapabilityEvidenceStatus.UNKNOWN:
        return status.value, _model_evidence_source(evidence.evidence_source)

    if capability is Capability.VISION_INPUT and model_info.supports_vision is not None:
        return (
            "supported" if model_info.supports_vision else "unsupported",
            _model_evidence_source(evidence.evidence_source),
        )
    if capability is Capability.REASONING_EFFORT:
        reasoning_status = model_info.reasoning.status
        if reasoning_status is not ReasoningCapabilityStatus.UNKNOWN:
            return (
                reasoning_status.value,
                _model_evidence_source(model_info.reasoning.evidence_source),
            )
        if model_info.supports_thinking is not None:
            return (
                "supported" if model_info.supports_thinking else "unsupported",
                _model_evidence_source(evidence.evidence_source),
            )
    return "unknown", _model_evidence_source(evidence.evidence_source)


def _model_evidence_source(source: str) -> str:
    return source if source != "unknown" else "model_metadata"


def _confidence_for_status(status: str) -> str:
    if status in {"supported", "unsupported"}:
        return "confirmed"
    if status == "accepted-but-unverified":
        return "unverified"
    return "unknown"


def _provider_isolation_receipt(policy: ProviderPolicy) -> dict[str, object]:
    """Return the launch policy preview without authorizing or contacting anything."""

    forbidden = sorted(policy.forbidden_provider_families)
    return {
        "primary_provider": policy.primary_provider,
        "primary_model": policy.primary_model,
        "mode": policy.mode.value,
        "paid_fallback": policy.paid_fallback,
        "allowed_local_tools": sorted(policy.allowed_local_tools),
        "forbidden_provider_families": forbidden,
        "fallback_decision": "blocked",
        "fallback_provider_families": forbidden,
        "network": "none",
    }


def _synthetic_request(model: str, shapes: Sequence[str]) -> MessagesRequest:
    shape_set = set(shapes)
    tools: list[Tool] = []
    if shape_set & {
        "tools",
        "parallel-tools",
        "browser",
        "macos",
        "screenshot",
    }:
        tool_name = "lookup"
        if "browser" in shape_set:
            tool_name = "browser_navigate"
        elif "macos" in shape_set:
            tool_name = "macos_click"
        elif "screenshot" in shape_set:
            tool_name = "screenshot"
        tools.append(
            Tool(
                name=tool_name,
                description="synthetic diagnostic tool",
                input_schema={"type": "object", "properties": {}},
            )
        )
        if "parallel-tools" in shape_set:
            tools.append(
                Tool(
                    name="lookup_second",
                    description="synthetic diagnostic tool",
                    input_schema={"type": "object", "properties": {}},
                )
            )

    content: str | list[dict[str, Any]] = "synthetic diagnostic request"
    if "vision" in shape_set:
        content = [
            {"type": "text", "text": "synthetic image request"},
            {
                "type": "image",
                "source": {"type": "url", "url": "https://example.invalid/image"},
            },
        ]
    if "image-tool-result" in shape_set:
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "synthetic_tool",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "https://example.invalid/screenshot",
                        },
                    }
                ],
            }
        ]
    request_data: dict[str, Any] = {
        "model": model,
        "messages": [Message(role="user", content=content)],
        "tools": tools or None,
        "thinking": {"enabled": True} if "reasoning" in shape_set else None,
        "output_config": {"format": {"type": "json_schema"}}
        if "structured" in shape_set
        else None,
    }
    if "parallel-tools" in shape_set:
        request_data["parallel_tool_calls"] = True
    return MessagesRequest.model_validate(request_data)


def _protocol_name(provider_id: str, model: str) -> str:
    if provider_id != "opencode_go":
        return "provider-defined"
    protocol = OPENCODE_GO_MODEL_PROTOCOLS.get(model)
    return protocol.value if protocol is not None else "unknown"


__all__ = [
    "SYNTHETIC_REQUEST_SHAPES",
    "build_route_diagnostic",
    "parse_synthetic_shapes",
]
