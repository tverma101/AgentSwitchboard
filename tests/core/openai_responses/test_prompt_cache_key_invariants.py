import json

from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.openai_responses.provider_input import (
    build_responses_provider_request,
)
from free_claude_code.core.reasoning import ReasoningPolicy


def test_session_cache_key_survives_turn_and_tool_schema_changes_without_prompt_leak(
) -> None:
    session_id = "stable-session-123"
    first = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "claude_session_id": session_id,
            "messages": [{"role": "user", "content": "first turn"}],
            "tools": [
                {
                    "name": "lookup",
                    "description": "Look up a value",
                    "input_schema": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                }
            ],
        }
    )
    later = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "claude_session_id": session_id,
            "messages": [
                {"role": "user", "content": "first turn"},
                {"role": "assistant", "content": "first answer"},
                {"role": "user", "content": "later turn"},
            ],
            "tools": [
                {
                    "name": "lookup",
                    "description": "Look up a value with an optional limit",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "q": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                    },
                }
            ],
        }
    )

    first_body = build_responses_provider_request(
        first,
        reasoning=ReasoningPolicy.provider_default(),
    )
    later_body = build_responses_provider_request(
        later,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert first_body["prompt_cache_key"] == session_id
    assert later_body["prompt_cache_key"] == session_id
    assert first_body["input"] != later_body["input"]
    assert first_body["tools"] != later_body["tools"]
    assert json.dumps(first_body).count(session_id) == 1
    assert json.dumps(later_body).count(session_id) == 1
