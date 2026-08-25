import json

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityHelper,
    CapabilityRoutingMode,
)
from free_claude_code.application.model_metadata import (
    CapabilityEvidence,
    CapabilityEvidenceStatus,
    ProviderModelInfo,
)
from free_claude_code.cli.diagnose import build_route_diagnostic
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    return Settings.model_construct(
        model="opencode_go/muse-spark-1.2-contributor",
        model_fable=None,
        model_opus=None,
        model_sonnet=None,
        model_haiku=None,
        model_aliases="",
        reasoning_policy=ReasoningPreference.CLIENT,
        reasoning_fable=ReasoningPreference.INHERIT,
        reasoning_opus=ReasoningPreference.INHERIT,
        reasoning_sonnet=ReasoningPreference.INHERIT,
        reasoning_haiku=ReasoningPreference.INHERIT,
    )


def test_route_diagnostic_is_zero_network_and_explains_muse_protocol() -> None:
    payload = build_route_diagnostic(_settings(), shapes=("text",))

    assert payload["network"] == "none"
    assert payload["billable_requests"] == 0
    assert payload["controller"]["provider"] == "opencode_go"
    assert payload["controller"]["model"] == "muse-spark-1.2-contributor"
    assert payload["controller"]["protocol"] == "responses"
    assert payload["decision"]["decision"] == "primary"
    assert payload["provider_isolation"] == {
        "primary_provider": "opencode_go",
        "primary_model": "muse-spark-1.2-contributor",
        "mode": "strict",
        "paid_fallback": False,
        "allowed_local_tools": ["browser", "computer"],
        "forbidden_provider_families": [
            "anthropic",
            "chatgpt",
            "codex",
            "openai",
        ],
        "fallback_decision": "blocked",
        "fallback_provider_families": [
            "anthropic",
            "chatgpt",
            "codex",
            "openai",
        ],
        "network": "none",
    }


def test_route_diagnostic_rejects_unknown_vision_before_provider_io() -> None:
    payload = build_route_diagnostic(_settings(), shapes=("vision",))

    assert payload["required"]["capabilities"] == [
        "text_input",
        "text_output",
        "vision_input",
    ]
    assert payload["capability_evidence"][-1] == {
        "capability": "vision_input",
        "state": "unknown",
        "evidence_status": "unknown",
        "confidence": "unknown",
        "evidence_source": "unknown",
    }
    assert payload["decision"]["decision"] == "rejected"
    assert "vision_input" in payload["decision"]["error"]


def test_route_diagnostic_can_explain_an_explicitly_evidenced_capability() -> None:
    payload = build_route_diagnostic(
        _settings(),
        shapes=("vision", "reasoning"),
        mode=CapabilityRoutingMode.STRICT,
        known_capabilities=frozenset(
            {Capability.VISION_INPUT, Capability.REASONING_EFFORT}
        ),
        supported_capabilities=frozenset(
            {Capability.VISION_INPUT, Capability.REASONING_EFFORT}
        ),
    )

    assert payload["decision"]["decision"] == "primary"
    assert {row["capability"]: row["state"] for row in payload["capability_evidence"]}[
        "reasoning_effort"
    ] == "supported"


def test_route_diagnostic_uses_cached_model_evidence_without_provider_io() -> None:
    payload = build_route_diagnostic(
        _settings(),
        shapes=("vision",),
        model_info=ProviderModelInfo(
            "muse-spark-1.2-contributor",
            capability_evidence=CapabilityEvidence(
                statuses=(("vision_input", CapabilityEvidenceStatus.SUPPORTED),),
                evidence_source="provider_catalog",
                observed_at="2026-08-24T00:00:00Z",
                evidence_version="catalog-1",
            ),
        ),
    )

    assert payload["decision"]["decision"] == "primary"
    assert payload["capability_evidence"][-1] == {
        "capability": "vision_input",
        "state": "supported",
        "evidence_status": "supported",
        "confidence": "confirmed",
        "evidence_source": "provider_catalog",
    }
    assert payload["effective_capabilities"] == {
        "evidence_source": "provider_catalog",
        "observed_at": "2026-08-24T00:00:00Z",
        "evidence_version": "catalog-1",
        "evidence_protocol": None,
        "states": {
            "text_input": "supported",
            "text_output": "supported",
            "vision_input": "supported",
        },
    }


def test_route_diagnostic_surfaces_an_allowlisted_helper_plan() -> None:
    helper = CapabilityHelper(
        helper_id="local-vision",
        provider_family="local",
        model_ref="local/vision",
        capabilities=frozenset({Capability.VISION_INPUT}),
        local=True,
    )

    payload = build_route_diagnostic(
        _settings(),
        shapes=("vision",),
        mode=CapabilityRoutingMode.SMART_LOCAL,
        helpers=(helper,),
        allowed_helpers=frozenset({"local-vision"}),
    )

    assert payload["policy"]["allowed_helpers"] == ["local-vision"]
    assert payload["decision"]["decision"] == "helpers"
    assert payload["decision"]["helpers"] == [
        {
            "helper_id": "local-vision",
            "provider_family": "local",
            "model_ref": "local/vision",
            "capabilities": ["vision_input"],
            "local": True,
            "billable": False,
        }
    ]


def test_route_diagnostic_output_is_json_serializable_without_request_content() -> None:
    payload = build_route_diagnostic(_settings(), shapes=("image-tool-result",))
    encoded = json.dumps(payload)

    assert "example.invalid" not in encoded
    assert "synthetic diagnostic request" not in encoded
