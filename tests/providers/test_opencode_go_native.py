"""Contracts for OpenCode Go native protocol routing."""

import pytest

from free_claude_code.application.errors import InvalidRequestError
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.anthropic.openai_tool_names import OpenAIToolNameCodec
from free_claude_code.core.fault_attribution import (
    AttemptEvidence,
    FaultConfidence,
    FaultDomain,
)
from free_claude_code.core.reasoning import (
    DEFAULT_REASONING_POLICY,
    ReasoningEffort,
    ReasoningPolicy,
)
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.opencode_go import (
    GO_MODEL_PROTOCOLS,
    GoProtocol,
    OpenCodeGoProvider,
    build_native_messages_body,
    protocol_for_model,
)
from free_claude_code.providers.opencode_go.provider import (
    _record_failure,
    _sse_event_types,
)


def test_go_protocol_manifest_matches_documented_2026_08_23_split() -> None:
    responses = {
        model
        for model, protocol in GO_MODEL_PROTOCOLS.items()
        if protocol is GoProtocol.RESPONSES
    }
    messages = {
        model
        for model, protocol in GO_MODEL_PROTOCOLS.items()
        if protocol is GoProtocol.MESSAGES
    }
    chat = {
        model
        for model, protocol in GO_MODEL_PROTOCOLS.items()
        if protocol is GoProtocol.CHAT
    }

    assert responses == {
        "grok-4.5",
        "gpt-5.6-luna",
        "muse-spark-1.2-contributor",
    }
    assert messages == {
        "minimax-m3",
        "minimax-m2.7",
        "minimax-m2.5",
        "qwen3.8-max",
        "qwen3.7-max",
        "qwen3.7-plus",
        "qwen3.6-plus",
    }
    assert chat == {
        "glm-5.3",
        "glm-5.2",
        "glm-5.1",
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.6",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
        "mimo-v2.5",
        "mimo-v2.5-pro",
        "hy3",
        "ox-alpha-free",
    }
    assert len(GO_MODEL_PROTOCOLS) == 23


def test_unknown_go_model_fails_closed_without_protocol_probe() -> None:
    with pytest.raises(InvalidRequestError, match="protocol is unknown"):
        protocol_for_model("future-model-not-in-manifest")


def test_explicit_provider_http_status_is_classified_without_guessing_transport() -> (
    None
):
    class AuthenticationProbeError(Exception):
        status_code = 401

    evidence = AttemptEvidence(
        turn_id="turn_auth",
        request_id="req_auth",
        protocol="responses",
        provider="OPENCODE_GO",
        model="muse-spark-1.2-contributor",
        attempt_number=1,
    )

    _record_failure(evidence, AuthenticationProbeError())

    assert evidence.http_status == 401
    assert evidence.fault_domain is FaultDomain.OPENCODE_GATEWAY
    assert evidence.confidence is FaultConfidence.HIGH
    assert evidence.evidence_codes == ["upstream_error:http_401"]


def test_native_messages_preserve_anthropic_cache_control_and_images() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "qwen3.7-plus",
            "max_tokens": 4096,
            "system": [
                {
                    "type": "text",
                    "text": "stable system prefix",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                            },
                        },
                        {
                            "type": "text",
                            "text": "inspect this",
                            "cache_control": {"type": "ephemeral"},
                        },
                    ],
                }
            ],
            "tools": [
                {
                    "name": "Read",
                    "description": "Read a file",
                    "input_schema": {"type": "object"},
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    )

    body = build_native_messages_body(request)

    assert body["stream"] is True
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][0]["content"][0]["source"]["data"] == "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    assert body["messages"][0]["content"][1]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][0]["cache_control"] == {"type": "ephemeral"}


def test_native_messages_reject_cross_protocol_extra_body() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "qwen3.7-plus",
            "messages": [{"role": "user", "content": "hi"}],
            "extra_body": {"cache_control": {"type": "ephemeral"}},
        }
    )

    with pytest.raises(InvalidRequestError, match="extra_body"):
        build_native_messages_body(request)


def test_responses_conversion_shortens_long_tool_names_for_muse() -> None:
    long_name = "mcp__very_long_namespace__" + "tool_component_" * 6
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": "use the tool"}],
            "tools": [
                {
                    "name": long_name,
                    "description": "Test tool",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        }
    )

    body = OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=DEFAULT_REASONING_POLICY,
    )

    wire_name = body["tools"][0]["name"]
    assert wire_name != long_name
    assert len(wire_name) <= 64


@pytest.mark.parametrize(
    "tool_choice",
    [
        {"type": "tool", "name": "Read"},
        {"type": "any"},
        {"type": "none"},
    ],
)
def test_muse_rejects_unsupported_tool_choice_before_provider_call(
    tool_choice: dict[str, str],
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "messages": [{"role": "user", "content": "use a tool"}],
            "tools": [
                {
                    "name": "Read",
                    "description": "Read a file",
                    "input_schema": {"type": "object"},
                }
            ],
            "tool_choice": tool_choice,
        }
    )

    with pytest.raises(InvalidRequestError, match=r"accepts only.*auto"):
        OpenCodeGoProvider._build_responses_body(
            request,
            reasoning=DEFAULT_REASONING_POLICY,
        )


def test_muse_tool_aliases_cover_exact_limit_and_collision_shapes() -> None:
    originals = (
        "a" * 64,
        "b" * 65,
        "collision_prefix_" + "x" * 80 + "a",
        "collision_prefix_" + "x" * 80 + "b",
    )
    codec = OpenAIToolNameCodec.from_names(originals)
    aliases = tuple(codec.encode(name) for name in originals)

    assert all(len(alias) <= 64 for alias in aliases)
    assert len(set(aliases)) == len(originals)
    assert tuple(codec.decode(alias) for alias in aliases) == originals


@pytest.mark.parametrize(
    ("effort", "expected_reasoning"),
    [
        (ReasoningEffort.MINIMAL, {"effort": "minimal", "summary": "auto"}),
        (ReasoningEffort.LOW, {"effort": "low", "summary": "auto"}),
        (ReasoningEffort.MEDIUM, {"effort": "medium", "summary": "auto"}),
        (ReasoningEffort.HIGH, {"effort": "high", "summary": "auto"}),
        (ReasoningEffort.XHIGH, {"effort": "xhigh", "summary": "auto"}),
        (ReasoningEffort.MAX, {"effort": "max", "summary": "auto"}),
    ],
)
def test_muse_responses_body_carries_each_reasoning_effort(
    effort: ReasoningEffort, expected_reasoning: dict[str, str]
) -> None:
    """The outgoing /responses body names the exact client-selected effort."""
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": "reason about this"}],
        }
    )

    body = OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=ReasoningPolicy.on(effort=effort),
    )

    assert body["model"] == "muse-spark-1.2-contributor"
    assert body["reasoning"] == expected_reasoning


def test_muse_responses_body_omits_reasoning_when_off() -> None:
    """Reasoning off must not name an effort in the outgoing body."""
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": "no reasoning"}],
        }
    )

    body = OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=ReasoningPolicy.off(),
    )

    assert body["reasoning"] == {"effort": "none"}


@pytest.mark.asyncio
async def test_native_protocols_share_one_hardened_transport_pool() -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid",
            max_concurrency=2,
        ),
        admission=ProviderAdmissionController(provider_name="OPENCODE_GO"),
    )
    try:
        assert provider._native_http._trust_env is False
        assert provider._native_http.follow_redirects is False
        assert provider._responses._client is provider._native_http
    finally:
        await provider.cleanup()


def test_messages_sse_receipt_extracts_types_without_data() -> None:
    chunk = (
        ": keep-alive\n\n"
        "event: content_block_delta\n"
        'data: {"delta":{"text":"secret"}}\n\n'
        "event: message_stop\n"
        "data: {}\n\n"
    )

    assert _sse_event_types(chunk) == ("content_block_delta", "message_stop")
    assert "secret" not in _sse_event_types(chunk)
