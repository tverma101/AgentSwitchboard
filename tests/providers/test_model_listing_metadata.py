from free_claude_code.application.model_metadata import ReasoningCapabilityStatus
from free_claude_code.providers.model_listing import extract_openai_model_infos


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
