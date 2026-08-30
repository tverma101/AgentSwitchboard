"""Provider-boundary contracts for Claude Code live user steering."""

from free_claude_code.core.anthropic.conversion import AnthropicToOpenAIConverter
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.openai_responses.provider_input import (
    build_responses_provider_request,
)
from free_claude_code.core.reasoning import ReasoningPolicy

_STEER = (
    "<system-reminder>\n"
    "The user sent a new message while you were working: STEER-B use path Y.\n"
    "</system-reminder>"
)


def _steered_request() -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": "configured-parent",
            "messages": [
                {"role": "user", "content": "TASK-A use path X."},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "inspect",
                            "input": {"path": "X"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_1",
                            "content": "inspection complete",
                        },
                        {"type": "text", "text": _STEER},
                    ],
                },
            ],
        }
    )


def test_responses_keeps_live_steering_after_tool_result_as_user_input() -> None:
    body = build_responses_provider_request(
        _steered_request(),
        reasoning=ReasoningPolicy.provider_default(),
    )

    tool_result_index = next(
        index
        for index, item in enumerate(body["input"])
        if item.get("type") == "function_call_output"
    )
    steer_index = next(
        index
        for index, item in enumerate(body["input"])
        if item.get("type") == "message"
        and item.get("role") == "user"
        and any(
            part.get("text") == _STEER
            for part in item.get("content", [])
            if isinstance(part, dict)
        )
    )

    assert steer_index > tool_result_index
    assert body["input"][steer_index] == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": _STEER}],
    }
    assert _STEER not in str(body["input"][tool_result_index]["output"])
    assert _STEER not in str(body.get("instructions", ""))


def test_openai_chat_keeps_live_steering_out_of_tool_output_and_system_role() -> None:
    messages = AnthropicToOpenAIConverter.convert_messages(_steered_request().messages)

    tool_result_index = next(
        index for index, message in enumerate(messages) if message.get("role") == "tool"
    )
    steer_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user" and message.get("content") == _STEER
    )

    assert steer_index > tool_result_index
    assert messages[steer_index] == {"role": "user", "content": _STEER}
    assert _STEER not in str(messages[tool_result_index].get("content", ""))
    assert not any(
        message.get("role") == "system" and _STEER in str(message.get("content", ""))
        for message in messages
    )
