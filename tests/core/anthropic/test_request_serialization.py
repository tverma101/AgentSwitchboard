"""Anthropic request parsing and public-field serialization."""

from free_claude_code.core.anthropic import dump_messages_request
from free_claude_code.core.anthropic.content import normalize_tool_result_content
from free_claude_code.core.anthropic.models import (
    ContentBlockServerToolUse,
    ContentBlockText,
    ContentBlockWebSearchToolResult,
    Message,
    MessagesRequest,
)
from free_claude_code.core.anthropic.request_serialization import (
    serialize_tool_result_content,
    tool_result_media_block_types,
)


def test_dump_preserves_public_fields_and_nested_extensions() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "m",
            "max_tokens": 20,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "hi",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
            "context_management": {"edits": [{"type": "clear"}]},
            "output_config": {"some": "hint"},
        }
    )

    body = dump_messages_request(request)

    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["context_management"] == {"edits": [{"type": "clear"}]}
    assert body["output_config"] == {"some": "hint"}


def test_dump_excludes_unknown_client_hints_and_fcc_routing_state() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "m",
            "messages": [{"role": "user", "content": "x"}],
            "reasoning_effort": "none",
            "unknown_client_hint": {"mode": "local"},
        }
    )
    request.original_model = "claude"
    request.resolved_provider_model = "upstream"

    body = dump_messages_request(request)

    assert "reasoning_effort" not in body
    assert "unknown_client_hint" not in body
    assert "original_model" not in body
    assert "resolved_provider_model" not in body


def test_pydantic_discriminator_still_distinguishes_blocks() -> None:
    message = Message.model_validate(
        {
            "role": "user",
            "content": [{"type": "text", "text": "a", "z": 1}],
        }
    )

    block = message.content[0]

    assert isinstance(block, ContentBlockText)
    assert block.model_dump()["z"] == 1


def test_server_tool_history_remains_valid_anthropic_input() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "m",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "server_tool_use",
                            "id": "srvtoolu_1",
                            "name": "web_search",
                            "input": {"query": "q"},
                        },
                        {
                            "type": "web_search_tool_result",
                            "tool_use_id": "srvtoolu_1",
                            "content": [],
                        },
                    ],
                }
            ],
        }
    )

    blocks = request.messages[0].content
    assert isinstance(blocks, list)
    assert isinstance(blocks[0], ContentBlockServerToolUse)
    assert isinstance(blocks[1], ContentBlockWebSearchToolResult)


def test_normalize_tool_result_content_unwraps_mcp_envelope() -> None:
    content = [
        {"type": "text", "text": "ready"},
        {"type": "image", "data": "encoded", "mimeType": "image/png"},
    ]
    envelope = {
        "content": content,
        "isError": False,
        "_meta": {"request_id": "metadata-is-not-model-content"},
    }

    assert normalize_tool_result_content(envelope) == content


def test_normalize_tool_result_content_leaves_application_mapping_untouched() -> None:
    application_value = {
        "content": [{"type": "text", "text": "business value"}],
        "status": "ok",
    }

    assert normalize_tool_result_content(application_value) is application_value


def test_tool_search_metadata_is_omitted_from_serialized_tool_results() -> None:
    content = [
        {"type": "tool_reference", "tool_name": "mcp__computer__click"},
        {"type": "text", "text": "usable result"},
    ]

    assert serialize_tool_result_content(content) == "usable result"
    assert tool_result_media_block_types(content) == ()
