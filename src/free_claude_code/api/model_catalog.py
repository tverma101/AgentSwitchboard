"""Model-list response construction for Claude-compatible clients."""

from typing import Literal

from pydantic import BaseModel, Field

from free_claude_code.application.model_metadata import (
    CapabilityEvidence,
    ReasoningCapabilityEvidence,
)
from free_claude_code.application.ports import RequestRuntimePort
from free_claude_code.config.model_aliases import parse_model_aliases
from free_claude_code.config.model_refs import (
    configured_chat_model_refs,
    parse_model_name,
    parse_provider_type,
)
from free_claude_code.config.model_visibility import filter_cached_model_infos
from free_claude_code.config.settings import Settings
from free_claude_code.core.gateway_model_ids import (
    gateway_model_id,
    no_thinking_gateway_model_id,
)

DISCOVERED_MODEL_CREATED_AT = "1970-01-01T00:00:00Z"


class ModelResponse(BaseModel):
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "free-claude-code"
    created_at: str
    display_name: str
    id: str
    type: Literal["model"] = "model"
    supports_vision: bool | None = None
    accepted_image_types: tuple[str, ...] = ()
    capability_evidence: dict[str, str] = Field(default_factory=dict)
    capability_evidence_source: str | None = None
    capability_evidence_observed_at: str | None = None
    capability_evidence_version: str | None = None
    capability_evidence_protocol: str | None = None
    reasoning_support: str | None = None
    reasoning_effort_evidence: dict[str, str] = Field(default_factory=dict)
    reasoning_default_effort: str | None = None
    reasoning_tokens_reported: bool | None = None
    reasoning_summary_emitted: bool | None = None
    reasoning_opaque_continuation: bool | None = None
    reasoning_evidence_source: str | None = None
    reasoning_evidence_date: str | None = None
    reasoning_evidence_version: str | None = None
    reasoning_evidence_protocol: str | None = None


class ModelsListResponse(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelResponse]
    first_id: str | None
    has_more: bool
    last_id: str | None


SUPPORTED_CLAUDE_MODELS = [
    ModelResponse(
        id="claude-fable-5",
        display_name="Claude Fable 5",
        created_at="2026-06-09T00:00:00Z",
    ),
    ModelResponse(
        id="claude-opus-4-20250514",
        display_name="Claude Opus 4",
        created_at="2025-05-14T00:00:00Z",
    ),
    ModelResponse(
        id="claude-sonnet-4-20250514",
        display_name="Claude Sonnet 4",
        created_at="2025-05-14T00:00:00Z",
    ),
    ModelResponse(
        id="claude-haiku-4-20250514",
        display_name="Claude Haiku 4",
        created_at="2025-05-14T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-opus-20240229",
        display_name="Claude 3 Opus",
        created_at="2024-02-29T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        created_at="2024-10-22T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-haiku-20240307",
        display_name="Claude 3 Haiku",
        created_at="2024-03-07T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-5-haiku-20241022",
        display_name="Claude 3.5 Haiku",
        created_at="2024-10-22T00:00:00Z",
    ),
]


def build_models_list_response(
    settings: Settings, runtime: RequestRuntimePort
) -> ModelsListResponse:
    """Return configured, cached, and compatibility model ids."""
    models: list[ModelResponse] = []
    seen: set[str] = set()

    for ref in configured_chat_model_refs(settings):
        model_info = runtime.cached_model_info(ref.provider_id, ref.model_id)
        _append_provider_model_variants(
            models,
            seen,
            ref.model_ref,
            supports_thinking=(
                model_info.supports_thinking if model_info is not None else None
            ),
            supports_vision=(
                model_info.supports_vision if model_info is not None else None
            ),
            accepted_image_types=(
                model_info.accepted_image_types if model_info is not None else ()
            ),
            capability_evidence=(
                model_info.capability_evidence if model_info is not None else None
            ),
            reasoning=(model_info.reasoning if model_info is not None else None),
        )

    for alias, target in parse_model_aliases(
        getattr(settings, "model_aliases", "")
    ).aliases.items():
        target_info = runtime.cached_model_info(
            parse_provider_type(target), parse_model_name(target)
        )
        alias_model = ModelResponse(
            id=alias,
            display_name=f"{alias} → {target}",
            created_at=DISCOVERED_MODEL_CREATED_AT,
            supports_vision=(
                target_info.supports_vision if target_info is not None else None
            ),
            accepted_image_types=(
                target_info.accepted_image_types if target_info is not None else ()
            ),
        )
        _apply_capability_fields(
            alias_model,
            target_info.capability_evidence if target_info is not None else None,
        )
        _apply_reasoning_fields(
            alias_model, target_info.reasoning if target_info is not None else None
        )
        _append_unique_model(models, seen, alias_model)

    for model_info in filter_cached_model_infos(
        settings, runtime.cached_prefixed_model_infos()
    ):
        _append_provider_model_variants(
            models,
            seen,
            model_info.model_id,
            supports_thinking=model_info.supports_thinking,
            supports_vision=model_info.supports_vision,
            accepted_image_types=model_info.accepted_image_types,
            capability_evidence=model_info.capability_evidence,
            reasoning=model_info.reasoning,
        )

    for model in SUPPORTED_CLAUDE_MODELS:
        _append_unique_model(models, seen, model)

    return ModelsListResponse(
        data=models,
        first_id=models[0].id if models else None,
        has_more=False,
        last_id=models[-1].id if models else None,
    )


def _discovered_model_response(
    model_id: str,
    *,
    display_name: str,
    supports_vision: bool | None = None,
    accepted_image_types: tuple[str, ...] = (),
    capability_evidence: CapabilityEvidence | None = None,
    reasoning: ReasoningCapabilityEvidence | None = None,
) -> ModelResponse:
    model = ModelResponse(
        id=model_id,
        display_name=display_name,
        created_at=DISCOVERED_MODEL_CREATED_AT,
        supports_vision=supports_vision,
        accepted_image_types=accepted_image_types,
    )
    _apply_capability_fields(model, capability_evidence)
    _apply_reasoning_fields(model, reasoning)
    return model


def _apply_capability_fields(
    model: ModelResponse, evidence: CapabilityEvidence | None
) -> None:
    if evidence is None:
        return
    model.capability_evidence = {
        capability: status.value for capability, status in evidence.statuses
    }
    model.capability_evidence_source = evidence.evidence_source
    model.capability_evidence_observed_at = evidence.observed_at
    model.capability_evidence_version = evidence.evidence_version
    model.capability_evidence_protocol = evidence.evidence_protocol


def _apply_reasoning_fields(
    model: ModelResponse,
    reasoning: ReasoningCapabilityEvidence | None,
) -> None:
    if reasoning is None:
        return
    model.reasoning_support = reasoning.status.value
    model.reasoning_effort_evidence = {
        effort: status.value for effort, status in reasoning.effort_evidence
    }
    model.reasoning_default_effort = reasoning.provider_default_effort
    model.reasoning_tokens_reported = reasoning.reports_reasoning_tokens
    model.reasoning_summary_emitted = reasoning.emits_visible_summary
    model.reasoning_opaque_continuation = reasoning.emits_opaque_continuation
    model.reasoning_evidence_source = reasoning.evidence_source
    model.reasoning_evidence_date = reasoning.evidence_date
    model.reasoning_evidence_version = reasoning.evidence_version
    model.reasoning_evidence_protocol = reasoning.evidence_protocol


def _append_unique_model(
    models: list[ModelResponse], seen: set[str], model: ModelResponse
) -> None:
    if model.id in seen:
        return
    seen.add(model.id)
    models.append(model)


def _append_provider_model_variants(
    models: list[ModelResponse],
    seen: set[str],
    provider_model_ref: str,
    *,
    supports_thinking: bool | None = None,
    supports_vision: bool | None = None,
    accepted_image_types: tuple[str, ...] = (),
    capability_evidence: CapabilityEvidence | None = None,
    reasoning: ReasoningCapabilityEvidence | None = None,
) -> None:
    if supports_thinking is not False:
        _append_unique_model(
            models,
            seen,
            _discovered_model_response(
                gateway_model_id(provider_model_ref),
                display_name=provider_model_ref,
                supports_vision=supports_vision,
                accepted_image_types=accepted_image_types,
                capability_evidence=capability_evidence,
                reasoning=reasoning,
            ),
        )
    _append_unique_model(
        models,
        seen,
        _discovered_model_response(
            no_thinking_gateway_model_id(provider_model_ref),
            display_name=f"{provider_model_ref} (no thinking)",
            supports_vision=supports_vision,
            accepted_image_types=accepted_image_types,
            capability_evidence=capability_evidence,
            reasoning=reasoning,
        ),
    )
