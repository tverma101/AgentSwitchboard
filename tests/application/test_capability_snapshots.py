import pytest

from free_claude_code.application.capability_snapshots import (
    CapabilityEvidenceConflictError,
    CapabilityEvidenceLayer,
    CapabilityEvidenceTier,
    litellm_model_snapshot,
    resolve_capability_evidence,
)
from free_claude_code.application.model_metadata import (
    CapabilityEvidence,
    CapabilityEvidenceStatus,
)


def _evidence(
    capability: str,
    status: CapabilityEvidenceStatus,
    source: str,
) -> CapabilityEvidence:
    return CapabilityEvidence(
        statuses=((capability, status),),
        evidence_source=source,
    )


def test_litellm_snapshot_maps_positive_claims_without_promoting_to_supported() -> None:
    snapshot = litellm_model_snapshot(
        "meta/muse-spark-1.2-contributor",
        {
            "max_input_tokens": 1_048_576,
            "supports_function_calling": True,
            "supports_parallel_function_calling": True,
            "supports_reasoning": True,
            "supports_response_schema": True,
            "supports_tool_choice": True,
            "supports_vision": True,
            "supported_modalities": ["text", "image", "video"],
            "supported_endpoints": [
                "/v1/chat/completions",
                "/v1/responses",
                "/v1/messages",
            ],
        },
        source_version="cdb60af0243d8c3aa3fe5531eb53b7364d4d5f27",
    )

    assert snapshot.max_input_tokens == 1_048_576
    assert snapshot.protocol_families == (
        "openai_chat",
        "openai_responses",
        "anthropic_messages",
    )
    evidence = snapshot.capability_evidence
    assert evidence.evidence_source == "trusted_snapshot:litellm"
    assert evidence.status_for("native_tools") is (
        CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    )
    assert evidence.status_for("parallel_tools") is (
        CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    )
    assert evidence.status_for("reasoning_effort") is (
        CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    )
    assert evidence.status_for("structured_output") is (
        CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    )
    assert evidence.status_for("named_tool_choice") is (
        CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    )
    assert evidence.status_for("vision_input") is (
        CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    )


def test_litellm_snapshot_preserves_explicit_negative_and_missing_unknown() -> None:
    snapshot = litellm_model_snapshot(
        "example/model",
        {
            "supports_vision": False,
            "supports_function_calling": False,
        },
        source_version="snapshot-1",
    )

    evidence = snapshot.capability_evidence
    assert evidence.status_for("vision_input") is CapabilityEvidenceStatus.UNSUPPORTED
    assert evidence.status_for("native_tools") is CapabilityEvidenceStatus.UNSUPPORTED
    assert evidence.status_for("reasoning_effort") is CapabilityEvidenceStatus.UNKNOWN
    assert snapshot.max_input_tokens is None
    assert snapshot.protocol_families == ()


def test_litellm_snapshot_rejects_internal_vision_conflict() -> None:
    with pytest.raises(CapabilityEvidenceConflictError, match="vision_input"):
        litellm_model_snapshot(
            "example/model",
            {
                "supports_vision": False,
                "supported_modalities": ["text", "image"],
            },
            source_version="snapshot-1",
        )


def test_precedence_is_override_provider_snapshot_family_unknown() -> None:
    layers = [
        CapabilityEvidenceLayer(
            CapabilityEvidenceTier.MODEL_FAMILY_HINT,
            _evidence(
                "vision_input",
                CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED,
                "family_hint",
            ),
        ),
        CapabilityEvidenceLayer(
            CapabilityEvidenceTier.TRUSTED_UPSTREAM_SNAPSHOT,
            _evidence(
                "vision_input",
                CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED,
                "trusted_snapshot:litellm",
            ),
        ),
        CapabilityEvidenceLayer(
            CapabilityEvidenceTier.PROVIDER_DISCOVERY,
            _evidence(
                "vision_input",
                CapabilityEvidenceStatus.SUPPORTED,
                "provider_metadata",
            ),
        ),
        CapabilityEvidenceLayer(
            CapabilityEvidenceTier.EXPLICIT_OVERRIDE,
            _evidence(
                "vision_input",
                CapabilityEvidenceStatus.UNSUPPORTED,
                "explicit_receipt_override",
            ),
        ),
    ]

    resolved = resolve_capability_evidence("vision_input", layers)

    assert resolved.tier is CapabilityEvidenceTier.EXPLICIT_OVERRIDE
    assert resolved.status is CapabilityEvidenceStatus.UNSUPPORTED
    assert resolved.evidence_sources == ("explicit_receipt_override",)
    assert len(resolved.conflicts) == 3
    assert {conflict.conflicting_source for conflict in resolved.conflicts} == {
        "provider_metadata",
        "trusted_snapshot:litellm",
        "family_hint",
    }


def test_provider_discovery_overrides_stale_snapshot_but_surfaces_disagreement() -> None:
    resolved = resolve_capability_evidence(
        "native_tools",
        [
            CapabilityEvidenceLayer(
                CapabilityEvidenceTier.TRUSTED_UPSTREAM_SNAPSHOT,
                _evidence(
                    "native_tools",
                    CapabilityEvidenceStatus.UNSUPPORTED,
                    "trusted_snapshot:litellm",
                ),
            ),
            CapabilityEvidenceLayer(
                CapabilityEvidenceTier.PROVIDER_DISCOVERY,
                _evidence(
                    "native_tools",
                    CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED,
                    "provider_metadata",
                ),
            ),
        ],
    )

    assert resolved.status is CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    assert resolved.evidence_sources == ("provider_metadata",)
    assert len(resolved.conflicts) == 1
    assert resolved.conflicts[0].conflicting_source == "trusted_snapshot:litellm"
    assert resolved.conflicts[0].conflicting_status is CapabilityEvidenceStatus.UNSUPPORTED


def test_equal_precedence_conflict_fails_instead_of_picking_permissive_claim() -> None:
    with pytest.raises(CapabilityEvidenceConflictError, match="equally authoritative"):
        resolve_capability_evidence(
            "vision_input",
            [
                CapabilityEvidenceLayer(
                    CapabilityEvidenceTier.PROVIDER_DISCOVERY,
                    _evidence(
                        "vision_input",
                        CapabilityEvidenceStatus.SUPPORTED,
                        "provider-a",
                    ),
                ),
                CapabilityEvidenceLayer(
                    CapabilityEvidenceTier.PROVIDER_DISCOVERY,
                    _evidence(
                        "vision_input",
                        CapabilityEvidenceStatus.UNSUPPORTED,
                        "provider-b",
                    ),
                ),
            ],
        )


def test_absent_evidence_remains_unknown() -> None:
    resolved = resolve_capability_evidence("pixel_computer_use", [])

    assert resolved.status is CapabilityEvidenceStatus.UNKNOWN
    assert resolved.tier is CapabilityEvidenceTier.UNKNOWN
    assert resolved.evidence_sources == ("unknown",)
    assert resolved.conflicts == ()
