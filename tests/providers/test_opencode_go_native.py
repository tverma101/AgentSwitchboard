"""Contracts for OpenCode Go native protocol routing."""

import pytest

from free_claude_code.application.errors import InvalidRequestError
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY
from free_claude_code.providers.opencode_go import (
    GO_MODEL_PROTOCOLS,
    GoProtocol,
    OpenCodeGoProvider,
    build_native_messages_body,
    protocol_for_model,
)


def test_go_protocol_manifest_matches_documented_2026_08_23_split() -> None:
    responses = {
        model for model, protocol in GO_MODEL_PROTOCOLS.items() if protocol is GoProtocol.RESPONSES
    }
    messages = {
        model for model, protocol in GO_MODEL_PROTOCOLS.items() if protocol is GoProtocol.MESSAGES
    }
    chat = {
        model for model, protocol in GO_MODEL_PROTOCOLS.items() if protocol is GoProtocol.CHAT
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
                                "data": "aGVsbG8=",
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
    assert body["messages"][0]["content"][0]["source"]["data"] == "aGVsbG8="
    assert body["messages"][0]["content"][1]["cache_control"] == {
        "type": "ephemeral"
    }
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
