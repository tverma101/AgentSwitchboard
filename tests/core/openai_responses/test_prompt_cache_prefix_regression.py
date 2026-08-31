from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.openai_responses.provider_input import (
    build_responses_provider_request,
)
from free_claude_code.core.reasoning import ReasoningPolicy


def test_later_turn_preserves_the_entire_prior_cacheable_prefix() -> None:
    session_id = "stable-session-123"
    tools = [
        {
            "name": "lookup",
            "description": "Look up a value",
            "input_schema": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
        }
    ]
    first = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "claude_session_id": session_id,
            "system": "Stable system instructions",
            "messages": [{"role": "user", "content": "first turn"}],
            "tools": tools,
        }
    )
    later = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "claude_session_id": session_id,
            "system": "Stable system instructions",
            "messages": [
                {"role": "user", "content": "first turn"},
                {"role": "assistant", "content": "first answer"},
                {"role": "user", "content": "later turn"},
            ],
            "tools": tools,
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
    assert first_body["instructions"] == later_body["instructions"]
    assert first_body["tools"] == later_body["tools"]
    first_input = first_body["input"]
    assert later_body["input"][: len(first_input)] == first_input
