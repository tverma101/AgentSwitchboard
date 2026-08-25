from typing import Any

from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.openai_responses import build_responses_provider_request
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY
from free_claude_code.providers.openai_chat import OPENAI_CHAT_PROFILES
from free_claude_code.providers.openai_chat.request_policy import (
    build_openai_chat_request_body,
)
from free_claude_code.providers.opencode_go import build_native_messages_body


# Regression provenance: https://github.com/musistudio/claude-code-router/issues/1643
def test_tool_association_survives_each_go_protocol_without_mutating_request() -> None:
    call_id = "call_normalization_contract"
    request = MessagesRequest.model_validate(
        {
            "model": "semantic-test-model",
            "max_tokens": 512,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Checking."},
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": "lookup",
                            "input": {"q": "value"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": {"answer": 42},
                        },
                        {"type": "text", "text": "Continue."},
                    ],
                },
            ],
            "tools": [
                {
                    "name": "lookup",
                    "description": "Look up one value.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                }
            ],
        }
    )
    original = request.model_dump(mode="python")

    messages_body = build_native_messages_body(request)
    responses_body = build_responses_provider_request(
        request,
        reasoning=DEFAULT_REASONING_POLICY,
    )
    chat_profile = OPENAI_CHAT_PROFILES["opencode_go"]
    chat_body = build_openai_chat_request_body(
        request,
        reasoning=DEFAULT_REASONING_POLICY,
        policy=chat_profile.request_policy,
        postprocessors=chat_profile.request_postprocessors,
    )

    assert _native_tool_association(messages_body) == (call_id, call_id)
    assert _responses_tool_association(responses_body) == (call_id, call_id)
    assert _chat_tool_association(chat_body) == (call_id, call_id)
    assert request.model_dump(mode="python") == original


def _native_tool_association(body: dict[str, Any]) -> tuple[str, str]:
    assistant = body["messages"][0]["content"]
    user = body["messages"][1]["content"]
    tool_use = next(block for block in assistant if block.get("type") == "tool_use")
    tool_result = next(block for block in user if block.get("type") == "tool_result")
    return str(tool_use["id"]), str(tool_result["tool_use_id"])


def _responses_tool_association(body: dict[str, Any]) -> tuple[str, str]:
    function_call = next(
        item for item in body["input"] if item.get("type") == "function_call"
    )
    function_output = next(
        item for item in body["input"] if item.get("type") == "function_call_output"
    )
    return str(function_call["call_id"]), str(function_output["call_id"])


def _chat_tool_association(body: dict[str, Any]) -> tuple[str, str]:
    assistant = next(
        message for message in body["messages"] if message.get("tool_calls")
    )
    tool_message = next(
        message for message in body["messages"] if message.get("role") == "tool"
    )
    tool_call = assistant["tool_calls"][0]
    return str(tool_call["id"]), str(tool_message["tool_call_id"])
