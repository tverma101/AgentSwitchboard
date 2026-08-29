import pytest

from free_claude_code.application.model_metadata import (
    CapabilityEvidenceStatus,
    ReasoningCapabilityStatus,
)
from free_claude_code.providers.model_listing import (
    ModelListResponseError,
    extract_openai_model_infos,
)


def test_openai_model_listing_preserves_explicit_vision_capabilities() -> None:
    infos = extract_openai_model_infos(
        {
            "data": [
                {
                    "id": "vision-model",
                    "capabilities": {
                        "vision": True,
                        "accepted_image_types": [
                            "image/png",
                            "image/webp",
                            "image/gif",
                        ],
                    },
                },
                {"id": "text-only", "capabilities": {"vision": False}},
            ]
        },
        provider_name="TEST",
    )

    by_id = {info.model_id: info for info in infos}
    assert by_id["vision-model"].supports_vision is True
    assert by_id["vision-model"].accepted_image_types == ("image/png", "image/webp")
    assert by_id["text-only"].supports_vision is False
    assert (
        by_id["vision-model"].capability_evidence.status_for("vision_input")
        is CapabilityEvidenceStatus.SUPPORTED
    )
    assert (
        by_id["vision-model"].capability_evidence.evidence_source == "provider_metadata"
    )


def test_openai_model_listing_preserves_free_and_pricing_metadata() -> None:
    infos = extract_openai_model_infos(
        {
            "data": [
                {
                    "id": "free-model",
                    "pricing": {
                        "prompt": "0",
                        "completion": "0",
                        "image": "0",
                    },
                },
                {
                    "id": "paid-model",
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                },
                {"id": "declared-free", "is_free": True},
            ]
        },
        provider_name="TEST",
    )

    by_id = {info.model_id: info for info in infos}
    assert by_id["free-model"].is_free is True
    assert by_id["free-model"].pricing == (
        ("completion", 0.0),
        ("image", 0.0),
        ("prompt", 0.0),
    )
    assert by_id["paid-model"].is_free is False
    assert by_id["declared-free"].is_free is True


def test_bai_model_listing_uses_optional_pricing_and_capability_metadata() -> None:
    infos = extract_openai_model_infos(
        {
            "data": [
                {
                    "id": "deepseek-v4-flash",
                    "object": "model",
                    "pricing": {"input": "0", "output": "0"},
                    "input_modalities": ["text"],
                },
                {
                    "id": "deepseek-v4-flash-vision-exp",
                    "object": "model",
                    "pricing": {"input": "0", "output": "0"},
                    "input_modalities": ["text", "image"],
                    "capabilities": {"vision": True},
                },
                {
                    "id": "paid-model",
                    "object": "model",
                    "pricing": {"input": "0.22", "output": "0.66"},
                },
                {
                    "id": "partial-price-model",
                    "object": "model",
                    "pricing": {"input": "0"},
                },
            ]
        },
        provider_name="BAI",
    )

    by_id = {info.model_id: info for info in infos}
    assert by_id["deepseek-v4-flash"].is_free is True
    assert by_id["deepseek-v4-flash"].supports_vision is None
    assert by_id["deepseek-v4-flash-vision-exp"].is_free is True
    assert by_id["deepseek-v4-flash-vision-exp"].supports_vision is True
    assert by_id["paid-model"].is_free is False
    assert by_id["partial-price-model"].is_free is None


def test_bai_minimal_model_listing_does_not_guess_price_or_vision() -> None:
    infos = extract_openai_model_infos(
        {"data": [{"id": "model-without-optional-metadata", "object": "model"}]},
        provider_name="BAI",
    )

    info = next(iter(infos))
    assert info.is_free is None
    assert info.pricing == ()
    assert info.supports_vision is None


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "supports_vision": False,
            "capabilities": {"vision": True},
        },
        {"supports_vision": False, "input_modalities": ["text", "image"]},
        {
            "supports_vision": False,
            "accepted_image_types": ["image/png"],
        },
        {
            "capabilities": {"tools": False},
            "supported_parameters": ["tools"],
        },
    ],
)
def test_openai_model_listing_rejects_conflicting_vision_metadata(
    metadata: dict[str, object],
) -> None:
    with pytest.raises(
        ModelListResponseError,
        match=r"conflicting .*capability metadata",
    ):
        extract_openai_model_infos(
            {"data": [{"id": "ambiguous-model", **metadata}]},
            provider_name="TEST",
        )


def test_openai_model_listing_keeps_reasoning_evidence_separate_from_acceptance() -> (
    None
):
    infos = extract_openai_model_infos(
        {
            "data": [
                {
                    "id": "muse",
                    "capabilities": {
                        "reasoning": True,
                        "reasoning_efforts": ["low", "high", "unsupported"],
                        "reports_reasoning_tokens": True,
                        "visible_summary": True,
                        "opaque_reasoning": True,
                        "reasoning_evidence_source": "live_receipt",
                        "reasoning_evidence_protocol": "responses",
                    },
                    "reasoning_default_effort": "low",
                },
                {
                    "id": "accepted-only",
                    "supported_parameters": ["reasoning"],
                },
            ]
        },
        provider_name="OPENCODE_GO",
    )

    by_id = {info.model_id: info for info in infos}
    muse = by_id["muse"].reasoning
    assert muse.status is ReasoningCapabilityStatus.SUPPORTED
    assert muse.status_for_effort("low") is ReasoningCapabilityStatus.SUPPORTED
    assert muse.status_for_effort("medium") is ReasoningCapabilityStatus.UNKNOWN
    assert muse.provider_default_effort == "low"
    assert muse.reports_reasoning_tokens is True
    assert muse.emits_visible_summary is True
    assert muse.emits_opaque_continuation is True
    assert muse.evidence_source == "live_receipt"
    assert muse.evidence_protocol == "responses"

    accepted = by_id["accepted-only"].reasoning
    assert accepted.status is ReasoningCapabilityStatus.ACCEPTED_BUT_UNVERIFIED
