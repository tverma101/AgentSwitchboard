import json

from free_claude_code.application.capabilities import Capability, CapabilityRoutingMode
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
        "allowed_helpers": [],
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
        "would_be_fallback": [
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
        "evidence_source": "cli-asserted",
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


def test_route_diagnostic_output_is_json_serializable_without_request_content() -> None:
    payload = build_route_diagnostic(_settings(), shapes=("image-tool-result",))
    encoded = json.dumps(payload)

    assert "example.invalid" not in encoded
    assert "synthetic diagnostic request" not in encoded
