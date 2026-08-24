"""Provider model-list response parsing helpers."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from free_claude_code.application.model_metadata import (
    CapabilityEvidence,
    CapabilityEvidenceStatus,
    ReasoningCapabilityEvidence,
    ReasoningCapabilityStatus,
)
from free_claude_code.application.model_metadata import (
    ProviderModelInfo as _ProviderModelInfo,
)


class ModelListResponseError(ValueError):
    """A provider model-list response cannot be parsed safely."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def model_infos_from_ids(
    model_ids: Iterable[str], *, supports_thinking: bool | None = None
) -> frozenset[_ProviderModelInfo]:
    """Build unknown-capability model metadata from plain provider model ids."""
    return frozenset(
        _ProviderModelInfo(model_id=model_id, supports_thinking=supports_thinking)
        for model_id in model_ids
        if model_id.strip()
    )


def extract_openai_model_infos(
    payload: Any, *, provider_name: str
) -> frozenset[_ProviderModelInfo]:
    """Extract model metadata from an OpenAI-compatible ``/models`` response."""
    model_infos: set[_ProviderModelInfo] = set()
    for item in model_list_items(payload, provider_name=provider_name):
        model_id = _field(item, "id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise _malformed(provider_name, "expected every data item to include id")
        supports_vision, accepted_image_types = _vision_metadata(
            item, provider_name=provider_name
        )
        raw_supported_parameters = _field(item, "supported_parameters")
        supported_parameters = (
            {param for param in raw_supported_parameters if isinstance(param, str)}
            if _is_sequence(raw_supported_parameters)
            else None
        )
        reasoning = _reasoning_metadata(item, supported_parameters=supported_parameters)
        capability_evidence = _capability_metadata(
            item,
            provider_name=provider_name,
            supports_vision=supports_vision,
            supported_parameters=supported_parameters,
        )
        model_infos.add(
            _ProviderModelInfo(
                model_id=model_id,
                supports_thinking=(
                    True
                    if reasoning.status
                    in {
                        ReasoningCapabilityStatus.SUPPORTED,
                        ReasoningCapabilityStatus.ACCEPTED_BUT_UNVERIFIED,
                    }
                    else False
                    if reasoning.status is ReasoningCapabilityStatus.UNSUPPORTED
                    else None
                ),
                supports_vision=supports_vision,
                accepted_image_types=accepted_image_types,
                reasoning=reasoning,
                capability_evidence=capability_evidence,
            )
        )

    if not model_infos:
        raise _malformed(provider_name, "response did not include any model ids")
    return frozenset(model_infos)


def extract_tool_capable_model_infos(
    payload: Any, *, provider_name: str
) -> frozenset[_ProviderModelInfo]:
    """Extract tool-capable models with ``supported_parameters`` metadata."""
    data = model_list_items(payload, provider_name=provider_name)

    model_infos: set[_ProviderModelInfo] = set()
    for item in data:
        model_id = _field(item, "id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise _malformed(provider_name, "expected every data item to include id")

        supported_parameters = _field(item, "supported_parameters")
        if not _is_sequence(supported_parameters):
            continue
        supported_parameter_names = {
            param for param in supported_parameters if isinstance(param, str)
        }
        if supported_parameter_names.isdisjoint({"tools", "tool_choice"}):
            continue
        reasoning = _reasoning_metadata(
            item, supported_parameters=supported_parameter_names
        )
        supports_vision, accepted_image_types = _vision_metadata(
            item, provider_name=provider_name
        )
        capability_evidence = _capability_metadata(
            item,
            provider_name=provider_name,
            supports_vision=supports_vision,
            supported_parameters=supported_parameter_names,
        )
        model_infos.add(
            _ProviderModelInfo(
                model_id=model_id,
                supports_thinking=(
                    "reasoning" in supported_parameter_names
                    or reasoning.status is ReasoningCapabilityStatus.SUPPORTED
                ),
                supports_vision=supports_vision,
                accepted_image_types=accepted_image_types,
                reasoning=reasoning,
                capability_evidence=capability_evidence,
            )
        )

    return frozenset(model_infos)


def model_list_items(payload: Any, *, provider_name: str) -> tuple[Any, ...]:
    """Return a validated OpenAI-shaped model-list data array."""
    data = _field(payload, "data")
    if not _is_sequence(data):
        raise _malformed(provider_name, "expected top-level data array")
    return tuple(data)


def _field(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

_CAPABILITY_FIELDS = {
    "text": "text_input",
    "tools": "native_tools",
    "parallel_tools": "parallel_tools",
    "parallel_tool_calls": "parallel_tools",
    "tool_choice": "named_tool_choice",
    "named_tool_choice": "named_tool_choice",
    "structured_output": "structured_output",
    "structured_outputs": "structured_output",
    "vision": "vision_input",
    "image_tool_results": "image_tool_results",
    "screenshot_vision": "screenshot_vision",
    "semantic_browser_control": "semantic_browser_control",
    "semantic_macos_control": "semantic_macos_control",
    "pixel_computer_use": "pixel_computer_use",
}
_SUPPORTED_PARAMETER_CAPABILITIES = {
    "tools": "native_tools",
    "tool_choice": "named_tool_choice",
    "parallel_tool_calls": "parallel_tools",
    "response_format": "structured_output",
    "structured_outputs": "structured_output",
    "reasoning": "reasoning_effort",
}


def _capability_metadata(
    item: Any,
    *,
    provider_name: str,
    supports_vision: bool | None,
    supported_parameters: set[str] | None,
) -> CapabilityEvidence:
    """Extract explicit capability states without provider-name inference."""
    capabilities = _field(item, "capabilities")
    capabilities = capabilities if isinstance(capabilities, Mapping) else {}
    claims: dict[str, CapabilityEvidenceStatus] = {}

    raw_statuses = _field(item, "capability_statuses")
    if raw_statuses is None:
        raw_statuses = capabilities.get("capability_statuses")
    if isinstance(raw_statuses, Mapping):
        for raw_name, raw_status in raw_statuses.items():
            capability = _CAPABILITY_FIELDS.get(str(raw_name), str(raw_name))
            status = _capability_status(raw_status)
            if status is not None:
                _record_capability_claim(
                    claims, capability, status, provider_name=provider_name
                )

    for raw_name, capability in _CAPABILITY_FIELDS.items():
        status = _capability_status(capabilities.get(raw_name))
        if status is not None:
            _record_capability_claim(
                claims, capability, status, provider_name=provider_name
            )

    if supports_vision is not None:
        _record_capability_claim(
            claims,
            "vision_input",
            (
                CapabilityEvidenceStatus.SUPPORTED
                if supports_vision
                else CapabilityEvidenceStatus.UNSUPPORTED
            ),
            provider_name=provider_name,
        )

    for parameter in supported_parameters or ():
        capability = _SUPPORTED_PARAMETER_CAPABILITIES.get(parameter)
        if capability is None:
            continue
        if claims.get(capability) is CapabilityEvidenceStatus.UNSUPPORTED:
            raise _malformed(
                provider_name,
                "conflicting capability metadata for "
                f"{capability!r}: explicit unsupported claim and "
                f"supported_parameters={parameter!r}",
            )
        if capability not in claims:
            claims[capability] = CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED

    source = _first_string(item, "capability_evidence_source")
    if source is None:
        source = _first_string(capabilities, "capability_evidence_source")
    if source is None:
        source = "provider_metadata" if claims else "unknown"
    observed_at = _first_string(item, "capability_observed_at", "observed_at")
    if observed_at is None:
        observed_at = _first_string(
            capabilities, "capability_observed_at", "observed_at"
        )
    version = _first_string(item, "capability_evidence_version") or _first_string(
        capabilities, "capability_evidence_version"
    )
    protocol = _first_string(item, "capability_evidence_protocol") or _first_string(
        capabilities, "capability_evidence_protocol"
    )
    return CapabilityEvidence(
        statuses=tuple(sorted(claims.items())),
        evidence_source=source,
        observed_at=observed_at,
        evidence_version=version,
        evidence_protocol=protocol,
    )


def _record_capability_claim(
    claims: dict[str, CapabilityEvidenceStatus],
    capability: str,
    status: CapabilityEvidenceStatus,
    *,
    provider_name: str,
) -> None:
    existing = claims.get(capability)
    if existing is not None and existing is not status:
        raise _malformed(
            provider_name,
            f"conflicting capability metadata for {capability!r}: "
            f"{existing.value} vs {status.value}",
        )
    claims[capability] = status


def _capability_status(value: Any) -> CapabilityEvidenceStatus | None:
    if isinstance(value, bool):
        return (
            CapabilityEvidenceStatus.SUPPORTED
            if value
            else CapabilityEvidenceStatus.UNSUPPORTED
        )
    if isinstance(value, str):
        try:
            return CapabilityEvidenceStatus(value.strip().casefold())
        except ValueError:
            return None
    return None


def _vision_metadata(
    item: Any, *, provider_name: str
) -> tuple[bool | None, tuple[str, ...]]:
    """Read optional model-list vision metadata without guessing from names."""
    vision_claims: list[tuple[str, bool]] = []
    explicit_supports_vision = _field(item, "supports_vision")
    if isinstance(explicit_supports_vision, bool):
        vision_claims.append(("supports_vision", explicit_supports_vision))
    accepted = _field(item, "accepted_image_types")
    capabilities = _field(item, "capabilities")
    if isinstance(capabilities, Mapping):
        if isinstance(capabilities.get("vision"), bool):
            vision_claims.append(("capabilities.vision", capabilities["vision"]))
        if accepted is None:
            accepted = capabilities.get("accepted_image_types")

    modalities = _field(item, "input_modalities")
    if isinstance(modalities, Sequence) and not isinstance(
        modalities, str | bytes | bytearray
    ):
        normalized = {str(value).casefold() for value in modalities}
        if normalized & {"image", "images", "vision"}:
            vision_claims.append(("input_modalities", True))

    accepted_types = (
        tuple(sorted(value for value in accepted if value in _IMAGE_TYPES))
        if isinstance(accepted, Sequence)
        and not isinstance(accepted, str | bytes | bytearray)
        else ()
    )
    if accepted_types:
        vision_claims.append(("accepted_image_types", True))
    claimed_values = {value for _, value in vision_claims}
    if len(claimed_values) > 1:
        claims = ", ".join(f"{source}={value}" for source, value in vision_claims)
        raise _malformed(
            provider_name,
            f"conflicting vision capability metadata ({claims})",
        )
    supports_vision = next(iter(claimed_values), None)
    return (
        supports_vision,
        accepted_types,
    )


_REASONING_EFFORTS = (
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)


def _reasoning_metadata(
    item: Any,
    *,
    supported_parameters: set[str] | None = None,
) -> ReasoningCapabilityEvidence:
    """Extract explicit reasoning evidence without inferring from model names."""

    capabilities = _field(item, "capabilities")
    capabilities = capabilities if isinstance(capabilities, Mapping) else {}
    raw_status = _field(item, "reasoning_status")
    if raw_status is None:
        raw_status = capabilities.get("reasoning_status")
    status = _reasoning_status(raw_status)
    if status is ReasoningCapabilityStatus.UNKNOWN:
        supported = _field(item, "supports_reasoning")
        if not isinstance(supported, bool):
            supported = _field(item, "supports_thinking")
        if not isinstance(supported, bool):
            supported = capabilities.get("reasoning")
        if isinstance(supported, bool):
            status = (
                ReasoningCapabilityStatus.SUPPORTED
                if supported
                else ReasoningCapabilityStatus.UNSUPPORTED
            )
        elif supported_parameters and "reasoning" in supported_parameters:
            status = ReasoningCapabilityStatus.ACCEPTED_BUT_UNVERIFIED

    raw_efforts = _first_field(
        item,
        "reasoning_efforts",
        "accepted_reasoning_efforts",
        "accepted_efforts",
    )
    if raw_efforts is None:
        raw_efforts = capabilities.get("reasoning_efforts")
    efforts = _normalized_efforts(raw_efforts)
    raw_effort_status = _first_field(item, "reasoning_effort_evidence")
    if raw_effort_status is None:
        raw_effort_status = capabilities.get("reasoning_effort_evidence")
    evidence = _effort_evidence(raw_effort_status, efforts, status)
    if not evidence and efforts:
        effort_status = (
            ReasoningCapabilityStatus.SUPPORTED
            if status is ReasoningCapabilityStatus.SUPPORTED
            else ReasoningCapabilityStatus.ACCEPTED_BUT_UNVERIFIED
        )
        evidence = tuple((effort, effort_status) for effort in efforts)

    default_effort = _first_string(
        item, "reasoning_default_effort", "provider_default_effort"
    )
    if default_effort is None:
        default_effort = _first_string(
            capabilities, "reasoning_default_effort", "provider_default_effort"
        )
    explicit_source = _first_string(item, "reasoning_evidence_source")
    if explicit_source is None:
        explicit_source = _first_string(capabilities, "reasoning_evidence_source")
    evidence_source = explicit_source or (
        "provider_metadata"
        if status is not ReasoningCapabilityStatus.UNKNOWN
        or evidence
        or default_effort is not None
        else "unknown"
    )
    return ReasoningCapabilityEvidence(
        status=status,
        effort_evidence=evidence,
        provider_default_effort=default_effort,
        reports_reasoning_tokens=_first_bool(
            item, capabilities, "reports_reasoning_tokens"
        ),
        emits_visible_summary=_first_bool(
            item, capabilities, "emits_visible_summary", "visible_summary"
        ),
        emits_opaque_continuation=_first_bool(
            item, capabilities, "emits_opaque_continuation", "opaque_reasoning"
        ),
        tool_compatible_efforts=_normalized_efforts(
            _first_field(item, "tool_compatible_reasoning_efforts")
            or capabilities.get("tool_compatible_reasoning_efforts")
        ),
        evidence_source=evidence_source,
        evidence_date=_first_string(item, "reasoning_evidence_date")
        or _first_string(capabilities, "reasoning_evidence_date"),
        evidence_version=_first_string(item, "reasoning_evidence_version")
        or _first_string(capabilities, "reasoning_evidence_version"),
        evidence_protocol=_first_string(item, "reasoning_evidence_protocol")
        or _first_string(capabilities, "reasoning_evidence_protocol"),
    )


def _reasoning_status(value: Any) -> ReasoningCapabilityStatus:
    if isinstance(value, str):
        try:
            return ReasoningCapabilityStatus(value.strip().lower())
        except ValueError:
            return ReasoningCapabilityStatus.UNKNOWN
    return ReasoningCapabilityStatus.UNKNOWN


def _normalized_efforts(value: Any) -> tuple[str, ...]:
    if not _is_sequence(value):
        return ()
    normalized = {
        str(effort).strip().lower()
        for effort in value
        if str(effort).strip().lower() in _REASONING_EFFORTS
    }
    return tuple(effort for effort in _REASONING_EFFORTS if effort in normalized)


def _effort_evidence(
    value: Any,
    efforts: tuple[str, ...],
    overall: ReasoningCapabilityStatus,
) -> tuple[tuple[str, ReasoningCapabilityStatus], ...]:
    if isinstance(value, Mapping):
        result: list[tuple[str, ReasoningCapabilityStatus]] = []
        for effort in _REASONING_EFFORTS:
            status = _reasoning_status(value.get(effort))
            if status is not ReasoningCapabilityStatus.UNKNOWN:
                result.append((effort, status))
        return tuple(result)
    if not efforts:
        return ()
    status = (
        ReasoningCapabilityStatus.SUPPORTED
        if overall is ReasoningCapabilityStatus.SUPPORTED
        else ReasoningCapabilityStatus.ACCEPTED_BUT_UNVERIFIED
    )
    return tuple((effort, status) for effort in efforts)


def _first_field(value: Any, *names: str) -> Any:
    for name in names:
        field = _field(value, name)
        if field is not None:
            return field
    return None


def _first_string(value: Any, *names: str) -> str | None:
    result = _first_field(value, *names)
    return result.strip() if isinstance(result, str) and result.strip() else None


def _first_bool(item: Any, capabilities: Mapping[str, Any], *names: str) -> bool | None:
    result = _first_field(item, *names)
    if not isinstance(result, bool):
        result = _first_field(capabilities, *names)
    return result if isinstance(result, bool) else None


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, str | bytes | bytearray
    )


def _malformed(provider_name: str, reason: str) -> ModelListResponseError:
    return ModelListResponseError(
        f"{provider_name} model-list response is malformed: {reason}"
    )
