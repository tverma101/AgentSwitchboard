"""Conservative adapters for manually pinned upstream capability snapshots."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from free_claude_code.application.model_metadata import (
    CapabilityEvidence,
    CapabilityEvidenceStatus,
)


class CapabilityEvidenceTier(IntEnum):
    """Explicit precedence for capability facts from weaker to stronger."""

    UNKNOWN = 0
    MODEL_FAMILY_HINT = 10
    TRUSTED_UPSTREAM_SNAPSHOT = 20
    PROVIDER_DISCOVERY = 30
    EXPLICIT_OVERRIDE = 40


@dataclass(frozen=True, slots=True)
class TrustedModelSnapshot:
    """Build/manual-time model facts imported from one pinned public catalog."""

    model_id: str
    max_input_tokens: int | None
    protocol_families: tuple[str, ...]
    capability_evidence: CapabilityEvidence


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceLayer:
    """One provenance-bearing capability record at a known precedence tier."""

    tier: CapabilityEvidenceTier
    evidence: CapabilityEvidence


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceConflict:
    """A lower-precedence source disagrees with the selected capability claim."""

    capability: str
    selected_status: CapabilityEvidenceStatus
    selected_source: str
    conflicting_status: CapabilityEvidenceStatus
    conflicting_source: str
    conflicting_tier: CapabilityEvidenceTier

    def as_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability,
            "selected_status": self.selected_status.value,
            "selected_source": self.selected_source,
            "conflicting_status": self.conflicting_status.value,
            "conflicting_source": self.conflicting_source,
            "conflicting_tier": self.conflicting_tier.name.casefold(),
        }


@dataclass(frozen=True, slots=True)
class ResolvedCapabilityEvidence:
    """One effective capability claim plus every weaker disagreement."""

    capability: str
    status: CapabilityEvidenceStatus
    tier: CapabilityEvidenceTier
    evidence_sources: tuple[str, ...]
    observed_at: str | None = None
    evidence_version: str | None = None
    evidence_protocol: str | None = None
    conflicts: tuple[CapabilityEvidenceConflict, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability,
            "status": self.status.value,
            "tier": self.tier.name.casefold(),
            "evidence_sources": list(self.evidence_sources),
            "observed_at": self.observed_at,
            "evidence_version": self.evidence_version,
            "evidence_protocol": self.evidence_protocol,
            "conflicts": [conflict.as_dict() for conflict in self.conflicts],
        }


class CapabilityEvidenceConflictError(ValueError):
    """Two equally authoritative sources make incompatible capability claims."""


_LITELLM_CAPABILITY_FIELDS = {
    "supports_function_calling": "native_tools",
    "supports_parallel_function_calling": "parallel_tools",
    "supports_tool_choice": "named_tool_choice",
    "supports_response_schema": "structured_output",
    "supports_vision": "vision_input",
    "supports_reasoning": "reasoning_effort",
}
_ENDPOINT_PROTOCOLS = {
    "/v1/messages": "anthropic_messages",
    "/v1/responses": "openai_responses",
    "/v1/chat/completions": "openai_chat",
}


def litellm_model_snapshot(
    model_id: str,
    entry: Mapping[str, Any],
    *,
    source_version: str,
    observed_at: str | None = None,
) -> TrustedModelSnapshot:
    """Map one pinned LiteLLM registry entry without trusting it as live proof.

    LiteLLM's public schema documents capability booleans as optional catalog
    claims. A positive snapshot claim therefore becomes
    ``accepted-but-unverified`` rather than ``supported``. An explicit false
    remains useful negative evidence. Missing fields remain unknown.
    """

    if not model_id.strip():
        raise ValueError("model_id is required")
    if not source_version.strip():
        raise ValueError("source_version is required")

    claims: dict[str, CapabilityEvidenceStatus] = {}
    for field, capability in _LITELLM_CAPABILITY_FIELDS.items():
        value = entry.get(field)
        if not isinstance(value, bool):
            continue
        _record_snapshot_claim(
            claims,
            capability,
            (
                CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
                if value
                else CapabilityEvidenceStatus.UNSUPPORTED
            ),
        )

    modalities = entry.get("supported_modalities")
    if _string_sequence_contains(modalities, "image"):
        _record_snapshot_claim(
            claims,
            "vision_input",
            CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED,
        )

    max_input_tokens = _positive_int(entry.get("max_input_tokens"))
    endpoints = entry.get("supported_endpoints")
    protocols = tuple(
        dict.fromkeys(
            _ENDPOINT_PROTOCOLS[endpoint]
            for endpoint in _string_sequence(endpoints)
            if endpoint in _ENDPOINT_PROTOCOLS
        )
    )
    return TrustedModelSnapshot(
        model_id=model_id,
        max_input_tokens=max_input_tokens,
        protocol_families=protocols,
        capability_evidence=CapabilityEvidence(
            statuses=tuple(sorted(claims.items())),
            evidence_source="trusted_snapshot:litellm",
            observed_at=observed_at,
            evidence_version=source_version,
        ),
    )


def resolve_capability_evidence(
    capability: str,
    layers: Sequence[CapabilityEvidenceLayer],
) -> ResolvedCapabilityEvidence:
    """Resolve one capability by explicit precedence while surfacing conflicts."""

    if not capability.strip():
        raise ValueError("capability is required")
    candidates = [
        layer
        for layer in layers
        if layer.evidence.status_for(capability) is not CapabilityEvidenceStatus.UNKNOWN
    ]
    if not candidates:
        return ResolvedCapabilityEvidence(
            capability=capability,
            status=CapabilityEvidenceStatus.UNKNOWN,
            tier=CapabilityEvidenceTier.UNKNOWN,
            evidence_sources=("unknown",),
        )

    highest_tier = max(layer.tier for layer in candidates)
    winners = [layer for layer in candidates if layer.tier == highest_tier]
    winner_statuses = {layer.evidence.status_for(capability) for layer in winners}
    if len(winner_statuses) != 1:
        details = ", ".join(
            f"{layer.evidence.evidence_source}="
            f"{layer.evidence.status_for(capability).value}"
            for layer in sorted(winners, key=lambda item: item.evidence.evidence_source)
        )
        raise CapabilityEvidenceConflictError(
            f"equally authoritative capability evidence conflicts for "
            f"{capability!r}: {details}"
        )

    selected_status = next(iter(winner_statuses))
    ordered_winners = sorted(winners, key=lambda item: item.evidence.evidence_source)
    selected_source = ordered_winners[0].evidence.evidence_source
    conflicts = tuple(
        CapabilityEvidenceConflict(
            capability=capability,
            selected_status=selected_status,
            selected_source=selected_source,
            conflicting_status=layer.evidence.status_for(capability),
            conflicting_source=layer.evidence.evidence_source,
            conflicting_tier=layer.tier,
        )
        for layer in sorted(
            (layer for layer in candidates if layer.tier < highest_tier),
            key=lambda item: (-int(item.tier), item.evidence.evidence_source),
        )
        if layer.evidence.status_for(capability) is not selected_status
    )
    return ResolvedCapabilityEvidence(
        capability=capability,
        status=selected_status,
        tier=highest_tier,
        evidence_sources=tuple(
            layer.evidence.evidence_source for layer in ordered_winners
        ),
        observed_at=_shared_value(
            layer.evidence.observed_at for layer in ordered_winners
        ),
        evidence_version=_shared_value(
            layer.evidence.evidence_version for layer in ordered_winners
        ),
        evidence_protocol=_shared_value(
            layer.evidence.evidence_protocol for layer in ordered_winners
        ),
        conflicts=conflicts,
    )


def _record_snapshot_claim(
    claims: dict[str, CapabilityEvidenceStatus],
    capability: str,
    status: CapabilityEvidenceStatus,
) -> None:
    current = claims.get(capability)
    if current is not None and current is not status:
        raise CapabilityEvidenceConflictError(
            f"trusted snapshot contains conflicting claims for {capability!r}: "
            f"{current.value} vs {status.value}"
        )
    claims[capability] = status


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _string_sequence_contains(value: Any, expected: str) -> bool:
    return expected in {item.casefold() for item in _string_sequence(value)}


def _shared_value(values: Iterable[str | None]) -> str | None:
    unique = {value for value in values if value is not None}
    if len(unique) == 1:
        return next(iter(unique))
    return None


__all__ = [
    "CapabilityEvidenceConflict",
    "CapabilityEvidenceConflictError",
    "CapabilityEvidenceLayer",
    "CapabilityEvidenceTier",
    "ResolvedCapabilityEvidence",
    "TrustedModelSnapshot",
    "litellm_model_snapshot",
    "resolve_capability_evidence",
]
