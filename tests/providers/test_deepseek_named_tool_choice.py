from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.reasoning import ReasoningPolicy
from free_claude_code.providers.deepseek.compat import build_deepseek_request_body


def test_deepseek_preserves_named_tool_choice() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "Read the file"}],
            "tools": [
                {
                    "name": "Read",
                    "description": "Read a file",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            "tool_choice": {"type": "tool", "name": "Read"},
        }
    )

    body = build_deepseek_request_body(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["tool_choice"] == {
        "type": "function",
        "function": {"name": "Read"},
    }
