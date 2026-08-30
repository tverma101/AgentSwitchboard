import json

import pytest

from free_claude_code.application.reasoning import client_reasoning_policy
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesRequest,
)
from free_claude_code.core.openai_responses.errors import ResponsesConversionError
from free_claude_code.core.openai_responses.provider_input import (
    build_responses_provider_request,
)
from free_claude_code.core.openai_responses.reasoning import reasoning_text_from_item
from free_claude_code.core.reasoning import ReasoningEffort, ReasoningPolicy

_KEEP_ALL_THINKING_EDIT = {
    "type": "clear_thinking_20251015",
    "keep": "all",
}


def test_reasoning_item_keeps_raw_content_and_provider_summary() -> None:
    assert (
        reasoning_text_from_item(
            {
                "type": "reasoning",
                "content": [{"type": "reasoning_text", "text": "raw trace"}],
                "summary": [{"type": "summary_text", "text": "user summary"}],
            }
        )
        == "raw trace\nuser summary"
    )


def test_reasoning_item_deduplicates_identical_raw_content_and_summary() -> None:
    assert (
        reasoning_text_from_item(
            {
                "type": "reasoning",
                "content": [{"type": "reasoning_text", "text": "same"}],
                "summary": [{"type": "summary_text", "text": "same"}],
            }
        )
        == "same"
    )


def test_build_responses_provider_request_preserves_multiturn_protocol() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "max_tokens": 4096,
            "system": "System instructions",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "summary"},
                        {"type": "redacted_thinking", "data": "opaque"},
                        {"type": "text", "text": "Calling a tool"},
                        {
                            "type": "tool_use",
                            "id": "call_1",
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
                            "tool_use_id": "call_1",
                            "content": {"answer": 42},
                        },
                        {"type": "text", "text": "Continue"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                            },
                        },
                    ],
                },
            ],
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
            "tool_choice": {"type": "tool", "name": "lookup"},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.on(effort=ReasoningEffort.XHIGH),
    )

    assert body["model"] == "gpt-test"
    assert body["instructions"] == "System instructions"
    assert body["max_output_tokens"] == 4096
    assert body["stream"] is True
    assert body["store"] is False
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert body["tool_choice"] == {"type": "function", "name": "lookup"}
    assert body["input"][0] == {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "summary"}],
        "encrypted_content": "opaque",
    }
    assert body["input"][1]["role"] == "assistant"
    assert body["input"][2] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "lookup",
        "arguments": json.dumps(
            {"q": "value"}, ensure_ascii=False, separators=(",", ":")
        ),
    }
    assert body["input"][3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"answer": 42}',
    }
    assert body["input"][4]["content"][1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    }


def test_responses_provider_can_mark_stable_instructions_for_prompt_caching() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-5.6-luna",
            "system": "Stable system instructions",
            "messages": [{"role": "user", "content": "Changing request"}],
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
        explicit_prompt_cache_breakpoint=True,
    )

    assert "instructions" not in body
    assert body["input"][0] == {
        "type": "message",
        "role": "developer",
        "content": [
            {
                "type": "input_text",
                "text": "Stable system instructions",
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        ],
    }
    assert body["input"][1]["role"] == "user"


def test_responses_provider_does_not_add_breakpoint_by_default() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "system": "Stable system instructions",
            "messages": [{"role": "user", "content": "Changing request"}],
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["instructions"] == "Stable system instructions"
    assert all(
        "prompt_cache_breakpoint" not in item
        for item in body["input"]
        if isinstance(item, dict)
    )


def test_responses_provider_filters_tool_search_controller_and_metadata() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_reference",
                            "tool_name": "mcp__computer__click",
                        },
                        {"type": "text", "text": "The tool is ready."},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "search_call",
                            "content": [
                                {
                                    "type": "tool_reference",
                                    "tool_name": "mcp__computer__click",
                                },
                                {"type": "text", "text": "Search metadata removed."},
                            ],
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "name": "tool_search_tool_regex",
                    "type": "tool_search_tool_regex_20251119",
                    "input_schema": {"type": "object"},
                },
                {
                    "name": "mcp__computer__click",
                    "description": "Click a visible control",
                    "input_schema": {"type": "object"},
                },
            ],
            "tool_choice": {"type": "tool", "name": "tool_search_tool_regex"},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert [tool["name"] for tool in body["tools"]] == ["mcp__computer__click"]
    assert body["tool_choice"] == "auto"
    output = next(
        item for item in body["input"] if item["type"] == "function_call_output"
    )
    assert output["output"] == "Search metadata removed."
    assert "tool_reference" not in json.dumps(body)


def test_build_responses_provider_request_preserves_image_inside_tool_result() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_image",
                            "name": "screenshot",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_image",
                            "content": [
                                {"type": "text", "text": "Screenshot captured."},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "url",
                                        "url": "https://example.test/shot.png",
                                    },
                                },
                            ],
                        }
                    ],
                },
            ],
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["input"][1] == {
        "type": "function_call_output",
        "call_id": "call_image",
        "output": [
            {"type": "input_text", "text": "Screenshot captured."},
            {"type": "input_image", "image_url": "https://example.test/shot.png"},
        ],
    }


def test_build_responses_provider_request_preserves_single_tool_result_image_block() -> (
    None
):
    """Accept the direct single-block shape emitted by some MCP bridges."""
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_single_image",
                            "name": "screenshot",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_single_image",
                            "content": {
                                "type": "image",
                                "source": {
                                    "type": "url",
                                    "url": "https://example.test/single-shot.png",
                                },
                            },
                        }
                    ],
                },
            ],
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["input"][1] == {
        "type": "function_call_output",
        "call_id": "call_single_image",
        "output": [
            {
                "type": "input_image",
                "image_url": "https://example.test/single-shot.png",
            }
        ],
    }


def test_build_responses_provider_request_preserves_native_mcp_image_shape() -> None:
    """Accept the direct image/data/mimeType block returned by the MCP bridge."""
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_native_image",
                            "name": "screenshot",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_native_image",
                            "content": {
                                "type": "image",
                                "data": (
                                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                                ),
                                "mimeType": "image/png",
                            },
                        }
                    ],
                },
            ],
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["input"][1] == {
        "type": "function_call_output",
        "call_id": "call_native_image",
        "output": [
            {
                "type": "input_image",
                "image_url": (
                    "data:image/png;base64,"
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                ),
            }
        ],
    }


@pytest.mark.parametrize(
    "tool_content",
    [
        {
            "content": [
                {"type": "text", "text": "Screenshot captured."},
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": "https://example.test/enveloped-shot.png",
                    },
                },
            ],
            "isError": False,
            "_meta": {"request_id": "metadata-is-not-model-content"},
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "result": {
                "content": [
                    {"type": "text", "text": "Screenshot captured."},
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "https://example.test/enveloped-shot.png",
                        },
                    },
                ],
                "isError": False,
            },
        },
    ],
)
def test_build_responses_provider_request_unwraps_mcp_result_envelope(
    tool_content: dict[str, object],
) -> None:
    """Preserve MCP screenshots when a bridge passes the complete result envelope."""
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_enveloped_image",
                            "name": "screenshot",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_enveloped_image",
                            "content": tool_content,
                        }
                    ],
                },
            ],
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["input"][1] == {
        "type": "function_call_output",
        "call_id": "call_enveloped_image",
        "output": [
            {"type": "input_text", "text": "Screenshot captured."},
            {
                "type": "input_image",
                "image_url": "https://example.test/enveloped-shot.png",
            },
        ],
    }


def test_build_responses_provider_request_unwraps_text_only_mcp_result() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_enveloped_text",
                            "name": "inspect",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_enveloped_text",
                            "content": {
                                "content": [{"type": "text", "text": "ready"}],
                                "isError": False,
                                "_meta": {},
                            },
                        }
                    ],
                },
            ],
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["input"][1]["output"] == "ready"


def test_build_responses_provider_request_rejects_unrepresentable_nested_media() -> (
    None
):
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_image",
                            "name": "screenshot",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_image",
                            "content": [
                                {
                                    "payload": {
                                        "type": "image",
                                        "source": {
                                            "type": "url",
                                            "url": "https://example.test/shot.png",
                                        },
                                    }
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    )

    with pytest.raises(ResponsesConversionError, match=r"structured media blocks"):
        build_responses_provider_request(
            request,
            reasoning=ReasoningPolicy.provider_default(),
        )


def test_responses_prompt_cache_key_prefers_explicit_caller_value() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "prompt_cache_key": "caller-key",
            "claude_session_id": "header-key",
            "metadata": {"user_id": "metadata-key"},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
        prompt_cache_key="parameter-key",
    )

    assert body["prompt_cache_key"] == "caller-key"


def test_responses_prompt_cache_key_uses_session_then_metadata_fallback() -> None:
    session_request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "claude_session_id": "header-key",
            "metadata": {"user_id": "metadata-key"},
        }
    )
    session_body = build_responses_provider_request(
        session_request,
        reasoning=ReasoningPolicy.provider_default(),
    )
    assert session_body["prompt_cache_key"] == "header-key"

    metadata_request = session_request.model_copy(update={"claude_session_id": None})
    metadata_body = build_responses_provider_request(
        metadata_request,
        reasoning=ReasoningPolicy.provider_default(),
    )
    assert metadata_body["prompt_cache_key"] == "metadata-key"


def test_responses_prompt_cache_key_ignores_unsafe_candidates() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "claude_session_id": "bad\nkey",
            "metadata": {"user_id": "fallback-key"},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["prompt_cache_key"] == "fallback-key"


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "hello",
        "Please summarize this private prompt",
        "req_123456",
        "turn-123456",
        "2026-08-24T12:00:00Z",
        "1724500000",
        "/Users/example/project",
        "sk-live-secret",
        "my-secret-value",
        "api_key_value",
        "550e8400-e29b-41d4-a716-446655440000",
    ],
)
def test_responses_prompt_cache_key_rejects_content_and_unstable_identifiers(
    unsafe_key: str,
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [
                {
                    "role": "user",
                    "content": "hello; Please summarize this private prompt",
                }
            ],
            "prompt_cache_key": unsafe_key,
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert "prompt_cache_key" not in body


def test_responses_prompt_cache_key_normalizes_stable_metadata_only_identity() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "prompt_cache_key": "  stable-session-key  ",
            "metadata": {"timestamp": "2026-08-24T12:00:00Z"},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["prompt_cache_key"] == "stable-session-key"
    assert body["input"][0]["content"][0]["text"] == "hello"


def test_responses_prompt_cache_key_uses_metadata_session_id_fallback() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"session_id": "metadata-session"},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["prompt_cache_key"] == "metadata-session"


def test_build_responses_provider_request_accepts_claude_client_controls() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"type": "adaptive", "display": "omitted"},
            "context_management": {"edits": [_KEEP_ALL_THINKING_EDIT]},
            "output_config": {"effort": "high"},
        }
    )
    snapshot = request.model_dump()

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.on(effort=ReasoningEffort.HIGH),
    )

    assert body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert "context_management" not in body
    assert "output_config" not in body
    assert request.model_dump() == snapshot


def test_build_responses_provider_request_uses_resolved_reasoning_policy() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "output_config": {"effort": "low"},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.on(effort=ReasoningEffort.MAX),
    )

    assert body["reasoning"] == {"effort": "max", "summary": "auto"}


@pytest.mark.parametrize("summary", ["auto", "concise", "detailed"])
def test_build_responses_provider_request_preserves_summary_mode(
    summary: str,
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "output_config": {"summary": summary},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["reasoning"] == {"summary": summary}


def test_build_responses_provider_request_combines_effort_and_summary_mode() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "output_config": {"summary": "concise"},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.on(effort=ReasoningEffort.HIGH),
    )

    assert body["reasoning"] == {"effort": "high", "summary": "concise"}


@pytest.mark.parametrize("summary", ["verbose", "", 1, None, {"mode": "auto"}])
def test_build_responses_provider_request_rejects_invalid_summary_mode(
    summary: object,
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "output_config": {"summary": summary},
        }
    )

    with pytest.raises(ResponsesConversionError, match=r"output_config\.summary"):
        build_responses_provider_request(
            request,
            reasoning=ReasoningPolicy.provider_default(),
        )


@pytest.mark.parametrize(
    "context_management",
    [
        None,
        {},
        {"edits": []},
        {"edits": [_KEEP_ALL_THINKING_EDIT]},
        {"edits": [_KEEP_ALL_THINKING_EDIT, _KEEP_ALL_THINKING_EDIT]},
    ],
)
def test_build_responses_provider_request_accepts_noop_context_management(
    context_management: dict[str, object] | None,
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "context_management": context_management,
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert "context_management" not in body


@pytest.mark.parametrize(
    "context_management",
    [
        {"edits": [{"type": "clear_thinking_20251015"}]},
        {
            "edits": [
                {
                    "type": "clear_thinking_20251015",
                    "keep": {"type": "thinking_turns", "value": 2},
                }
            ]
        },
        {"edits": [{"type": "clear_tool_uses_20250919"}]},
        {"edits": [{"type": "unknown_edit", "keep": "all"}]},
        {
            "edits": [
                {
                    **_KEEP_ALL_THINKING_EDIT,
                    "extra": True,
                }
            ]
        },
        {"edits": [], "extra": True},
        {"edits": None},
        {"edits": {}},
        {"edits": "not-a-list"},
    ],
)
def test_build_responses_provider_request_rejects_active_or_malformed_context(
    context_management: dict[str, object],
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "context_management": context_management,
        }
    )

    with pytest.raises(ResponsesConversionError, match="context_management"):
        build_responses_provider_request(
            request,
            reasoning=ReasoningPolicy.provider_default(),
        )


@pytest.mark.parametrize(
    ("effort", "reasoning", "expected"),
    [
        (
            "high",
            ReasoningPolicy.on(effort=ReasoningEffort.HIGH),
            {"effort": "high", "summary": "auto"},
        ),
        ("none", ReasoningPolicy.off(), {"effort": "none"}),
        ("future", ReasoningPolicy.provider_default(), None),
    ],
)
def test_build_responses_provider_request_accepts_application_owned_effort(
    effort: str,
    reasoning: ReasoningPolicy,
    expected: dict[str, str] | None,
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "output_config": {"effort": effort},
        }
    )

    body = build_responses_provider_request(request, reasoning=reasoning)

    assert body.get("reasoning") == expected
    assert "output_config" not in body


@pytest.mark.parametrize(
    ("output_config", "unsupported_path"),
    [
        ({"format": {"type": "json_schema"}}, "output_config.format"),
        (
            {"effort": "high", "format": {"type": "json_schema"}},
            "output_config.format",
        ),
        ({"future_control": True}, "output_config.future_control"),
    ],
)
def test_build_responses_provider_request_rejects_unconsumed_output_config(
    output_config: dict[str, object],
    unsupported_path: str,
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "output_config": output_config,
        }
    )

    with pytest.raises(ResponsesConversionError, match=unsupported_path):
        build_responses_provider_request(
            request,
            reasoning=ReasoningPolicy.provider_default(),
        )


def test_responses_provider_request_uses_one_portable_tool_alias() -> None:
    original = "mcp__responses_provider__" + "x" * 70
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_1",
                            "name": original,
                            "input": {"q": "value"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_1",
                            "content": "done",
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "name": original,
                    "description": "Long tool",
                    "input_schema": {"type": "object"},
                },
                {"name": "safe_tool", "input_schema": {"type": "object"}},
            ],
            "tool_choice": {"type": "tool", "name": original},
        }
    )
    snapshot = request.model_dump()

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    alias = body["tools"][0]["name"]
    assert alias != original
    assert len(alias) <= 64
    assert body["tools"][1]["name"] == "safe_tool"
    assert body["tool_choice"] == {"type": "function", "name": alias}
    function_call = next(
        item for item in body["input"] if item["type"] == "function_call"
    )
    assert function_call["name"] == alias
    assert function_call["call_id"] == "call_1"
    assert function_call["arguments"] == '{"q":"value"}'
    assert request.model_dump() == snapshot


def test_responses_round_trip_preserves_encrypted_reasoning_and_tool_ids() -> None:
    adapter = OpenAIResponsesAdapter()
    ingress = OpenAIResponsesRequest.model_validate(
        {
            "model": "openai/gpt-test",
            "input": [
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "Use a tool."}],
                    "encrypted_content": "opaque-reasoning",
                },
                {
                    "type": "function_call",
                    "call_id": "call_stable",
                    "name": "lookup",
                    "arguments": '{"q":"value"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_stable",
                    "output": "done",
                },
            ],
        }
    )
    anthropic = MessagesRequest.model_validate(adapter.to_anthropic_payload(ingress))

    body = build_responses_provider_request(
        anthropic,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["input"][:3] == [
        {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "Use a tool."}],
            "encrypted_content": "opaque-reasoning",
        },
        {
            "type": "function_call",
            "call_id": "call_stable",
            "name": "lookup",
            "arguments": '{"q":"value"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_stable",
            "output": "done",
        },
    ]


def test_responses_reasoning_round_trip_reaches_provider_request() -> None:
    adapter = OpenAIResponsesAdapter()
    ingress = OpenAIResponsesRequest.model_validate(
        {
            "model": "openai/gpt-test",
            "input": "hello",
            "reasoning": {"effort": "high"},
        }
    )
    anthropic = MessagesRequest.model_validate(adapter.to_anthropic_payload(ingress))

    body = build_responses_provider_request(
        anthropic,
        reasoning=client_reasoning_policy(anthropic),
    )

    assert body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert "output_config" not in body


@pytest.mark.parametrize("summary", ["auto", "concise", "detailed"])
def test_responses_reasoning_summary_round_trip_reaches_provider_request(
    summary: str,
) -> None:
    adapter = OpenAIResponsesAdapter()
    ingress = OpenAIResponsesRequest.model_validate(
        {
            "model": "openai/gpt-test",
            "input": "hello",
            "reasoning": {"summary": summary},
        }
    )
    anthropic = MessagesRequest.model_validate(adapter.to_anthropic_payload(ingress))

    assert anthropic.output_config == {"summary": summary}
    body = build_responses_provider_request(
        anthropic,
        reasoning=client_reasoning_policy(anthropic),
    )

    assert body["reasoning"] == {"summary": summary}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stop_sequences", ["stop"]),
        ("top_k", 4),
        ("mcp_servers", [{"name": "server"}]),
        ("extra_body", {"unknown": True}),
    ],
)
def test_build_responses_provider_request_rejects_lossy_fields(
    field: str, value: object
) -> None:
    payload = {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hello"}],
        field: value,
    }

    with pytest.raises(ResponsesConversionError, match=field):
        build_responses_provider_request(
            MessagesRequest.model_validate(payload),
            reasoning=ReasoningPolicy.provider_default(),
        )


def test_build_responses_provider_request_rejects_provider_managed_tools() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [
                {
                    "name": "web_search",
                    "type": "web_search_20250305",
                    "input_schema": {"type": "object"},
                }
            ],
        }
    )

    with pytest.raises(ResponsesConversionError, match="web_search_20250305"):
        build_responses_provider_request(
            request,
            reasoning=ReasoningPolicy.provider_default(),
        )


def test_build_responses_provider_request_rejects_unknown_request_fields() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "future_field": True,
        }
    )

    with pytest.raises(ResponsesConversionError, match="future_field"):
        build_responses_provider_request(
            request,
            reasoning=ReasoningPolicy.provider_default(),
        )
