import pytest

from free_claude_code.core.anthropic.openai_tool_names import OpenAIToolNameCodec
from free_claude_code.core.anthropic.stream_contracts import (
    assert_anthropic_stream_contract,
    parse_sse_text,
    thinking_content,
)
from free_claude_code.core.openai_responses.provider_stream import (
    ResponsesProviderStream,
    ResponsesStreamFailure,
)


def test_responses_provider_stream_preserves_reasoning_tools_usage_and_ids() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="openai/gpt-test",
        input_tokens=12,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.output_item.added",
            {
                "item": {
                    "type": "reasoning",
                    "id": "rs_1",
                }
            },
        )
    )
    output.extend(
        stream.feed(
            "response.reasoning_summary_text.delta",
            {"item_id": "rs_1", "delta": "reasoning"},
        )
    )
    output.extend(
        stream.feed(
            "response.output_item.done",
            {
                "item": {
                    "type": "reasoning",
                    "id": "rs_1",
                    "encrypted_content": "opaque",
                }
            },
        )
    )
    output.extend(
        stream.feed(
            "response.output_item.added",
            {
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "lookup",
                }
            },
        )
    )
    output.extend(
        stream.feed(
            "response.function_call_arguments.delta",
            {"item_id": "fc_1", "delta": '{"q":'},
        )
    )
    output.extend(
        stream.feed(
            "response.function_call_arguments.delta",
            {"item_id": "fc_1", "delta": '"x"}'},
        )
    )
    output.extend(
        stream.feed(
            "response.function_call_arguments.done",
            {"item_id": "fc_1", "arguments": '{"q":"x"}'},
        )
    )
    output.extend(
        stream.feed(
            "response.output_item.done",
            {
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": '{"q":"x"}',
                }
            },
        )
    )
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 8,
                        "input_tokens_details": {
                            "cached_tokens": 15,
                            "cache_write_tokens": 4,
                        },
                    }
                }
            },
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == "reasoning"
    assert stream.provider_reasoning_item is True
    assert stream.provider_visible_reasoning_summary is True
    assert stream.provider_reasoning_text is False
    assert stream.provider_opaque_reasoning is True
    assert stream.opaque_reasoning_hash is not None
    assert stream.harness_thinking_block is True
    assert stream.harness_thinking_delta is True
    starts = [
        event.data["content_block"]
        for event in events
        if event.event == "content_block_start"
    ]
    assert {"type": "redacted_thinking", "data": "opaque"} in starts
    assert {
        "type": "tool_use",
        "id": "call_1",
        "name": "lookup",
        "input": {},
    } in starts
    argument_deltas = [
        event.data["delta"]["partial_json"]
        for event in events
        if event.data.get("delta", {}).get("type") == "input_json_delta"
    ]
    assert argument_deltas == ['{"q":', '"x"}']
    message_delta = next(event for event in events if event.event == "message_delta")
    assert message_delta.data["usage"] == {
        "input_tokens": 5,
        "output_tokens": 8,
        "cache_read_input_tokens": 15,
        "cache_creation_input_tokens": 4,
    }


def test_responses_provider_stream_keeps_opaque_reasoning_without_fabricating_summary() -> (
    None
):
    stream = ResponsesProviderStream(
        message_id="msg_opaque",
        model="muse-spark-1.2-contributor",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.output_item.added",
            {"item": {"type": "reasoning", "id": "rs_opaque"}},
        )
    )
    output.extend(
        stream.feed(
            "response.output_item.done",
            {
                "item": {
                    "type": "reasoning",
                    "id": "rs_opaque",
                    "encrypted_content": "opaque-only",
                }
            },
        )
    )
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 2,
                        "output_tokens_details": {"reasoning_tokens": 1},
                    }
                }
            },
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == ""
    assert stream.provider_visible_reasoning_summary is False
    assert stream.provider_reasoning_text is False
    assert stream.usage_reasoning_tokens == 1
    assert stream.harness_thinking_block is True
    assert stream.harness_thinking_delta is False


def test_responses_provider_stream_keeps_raw_reasoning_distinct_from_summary() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_raw_reasoning",
        model="muse-spark-1.2-contributor",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.output_item.added",
            {"item": {"type": "reasoning", "id": "rs_raw"}},
        )
    )
    output.extend(
        stream.feed(
            "response.reasoning_text.delta",
            {"item_id": "rs_raw", "delta": "raw reasoning"},
        )
    )
    output.extend(
        stream.feed("response.output_text.delta", {"delta": "visible answer"})
    )
    output.extend(
        stream.feed(
            "response.completed",
            {"response": {"usage": {"input_tokens": 1, "output_tokens": 2}}},
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == "raw reasoning"
    assert stream.provider_reasoning_item is True
    assert stream.provider_visible_reasoning_summary is False
    assert stream.provider_reasoning_text is True
    assert stream.provider_opaque_reasoning is False
    assert stream.harness_thinking_block is True
    assert stream.harness_thinking_delta is True


def test_responses_provider_stream_does_not_fabricate_reasoning_without_state() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_reasoning_item_only",
        model="muse-spark-1.2-contributor",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.output_item.added",
            {"item": {"type": "reasoning", "id": "rs_empty"}},
        )
    )
    output.extend(
        stream.feed("response.output_text.delta", {"delta": "visible answer"})
    )
    output.extend(
        stream.feed(
            "response.completed",
            {"response": {"usage": {"input_tokens": 1, "output_tokens": 2}}},
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == ""
    assert stream.provider_reasoning_item is True
    assert stream.provider_visible_reasoning_summary is False
    assert stream.provider_reasoning_text is False
    assert stream.provider_opaque_reasoning is False
    assert stream.harness_thinking_block is False
    assert stream.harness_thinking_delta is False


def test_responses_provider_stream_rejects_invalid_tool_json() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="muse-spark-1.2-contributor",
        input_tokens=0,
    )
    stream.feed(
        "response.output_item.added",
        {
            "item": {
                "type": "function_call",
                "id": "fc_invalid",
                "call_id": "call_invalid",
                "name": "lookup",
            }
        },
    )

    with pytest.raises(ResponsesStreamFailure, match="valid JSON") as exc_info:
        stream.feed(
            "response.function_call_arguments.done",
            {"item_id": "fc_invalid", "arguments": '{"query":'},
        )

    assert exc_info.value.code == "invalid_tool_arguments"
    assert not stream.completed


@pytest.mark.parametrize("split_at", range(len('{"query":"value"}') + 1))
def test_responses_provider_stream_accepts_tool_json_split_at_every_boundary(
    split_at: int,
) -> None:
    arguments = '{"query":"value"}'
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="muse-spark-1.2-contributor",
        input_tokens=0,
    )
    stream.feed(
        "response.output_item.added",
        {
            "item": {
                "type": "function_call",
                "id": "fc_split",
                "call_id": "call_split",
                "name": "lookup",
            }
        },
    )
    for part in (arguments[:split_at], arguments[split_at:]):
        if part:
            stream.feed(
                "response.function_call_arguments.delta",
                {"item_id": "fc_split", "delta": part},
            )
    stream.feed(
        "response.output_item.done",
        {
            "item": {
                "type": "function_call",
                "id": "fc_split",
                "call_id": "call_split",
                "name": "lookup",
                "arguments": arguments,
            }
        },
    )
    stream.feed(
        "response.completed",
        {"response": {"usage": {"input_tokens": 1, "output_tokens": 1}}},
    )

    assert stream.completed
    assert stream.complete_tool_calls is True
    assert stream.valid_tool_json is True


def test_responses_provider_stream_rejects_complete_tool_without_item_terminal() -> (
    None
):
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="muse-spark-1.2-contributor",
        input_tokens=0,
    )
    stream.feed(
        "response.output_item.added",
        {
            "item": {
                "type": "function_call",
                "id": "fc_no_done",
                "call_id": "call_no_done",
                "name": "lookup",
            }
        },
    )
    stream.feed(
        "response.function_call_arguments.delta",
        {"item_id": "fc_no_done", "delta": "{}"},
    )

    with pytest.raises(
        ResponsesStreamFailure, match="output-item terminal"
    ) as exc_info:
        stream.feed(
            "response.completed",
            {"response": {"usage": {"input_tokens": 1, "output_tokens": 1}}},
        )

    assert exc_info.value.code == "missing_tool_terminal"
    assert not stream.completed


def test_responses_provider_stream_does_not_mark_close_without_terminal_as_success() -> (
    None
):
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="muse-spark-1.2-contributor",
        input_tokens=0,
    )
    stream.feed("response.output_text.delta", {"delta": "visible"})

    assert stream.generated_output
    assert stream.completed is False
    assert stream.terminal_event is None


def test_responses_provider_stream_records_missing_upstream_id_and_novel_incomplete_reason() -> (
    None
):
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="muse-spark-1.2-contributor",
        input_tokens=0,
    )
    output = stream.start()
    output.extend(stream.feed("response.output_text.delta", {"delta": "partial"}))
    output.extend(
        stream.feed(
            "response.incomplete",
            {
                "response": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "novel_provider_reason"},
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                }
            },
        )
    )

    assert stream.completed
    assert stream.upstream_response_id is None
    events = parse_sse_text("".join(output))
    message_delta = next(event for event in events if event.event == "message_delta")
    assert message_delta.data["delta"]["stop_reason"] == "max_tokens"


def test_responses_provider_stream_does_not_fabricate_empty_success() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="muse-spark-1.2-contributor",
        input_tokens=0,
    )

    with pytest.raises(ResponsesStreamFailure, match="without output") as exc_info:
        stream.feed(
            "response.completed",
            {"response": {"usage": {"input_tokens": 0, "output_tokens": 0}}},
        )

    assert exc_info.value.code == "empty_completed_response"
    assert not stream.completed


def test_responses_provider_stream_handles_parallel_tool_calls() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="muse-spark-1.2-contributor",
        input_tokens=0,
    )
    output = stream.start()
    for index, arguments in enumerate(('{"path":"a"}', '{"path":"b"}')):
        item_id = f"fc_{index}"
        output.extend(
            stream.feed(
                "response.output_item.added",
                {
                    "item": {
                        "type": "function_call",
                        "id": item_id,
                        "call_id": f"call_{index}",
                        "name": "lookup",
                    }
                },
            )
        )
        output.extend(
            stream.feed(
                "response.function_call_arguments.delta",
                {"item_id": item_id, "delta": arguments},
            )
        )
        output.extend(
            stream.feed(
                "response.function_call_arguments.done",
                {"item_id": item_id, "arguments": arguments},
            )
        )
        output.extend(
            stream.feed(
                "response.output_item.done",
                {
                    "item": {
                        "type": "function_call",
                        "id": item_id,
                        "call_id": f"call_{index}",
                        "name": "lookup",
                        "arguments": arguments,
                    }
                },
            )
        )
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "id": "resp_parallel",
                    "usage": {"input_tokens": 2, "output_tokens": 12},
                }
            },
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert stream.tool_call_count == 2
    assert stream.complete_tool_calls is True
    assert stream.valid_tool_json is True
    assert stream.upstream_response_id == "resp_parallel"


def test_responses_provider_stream_maps_real_cache_write_counter() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="openai/gpt-test",
        input_tokens=0,
    )
    output = stream.start()
    output.extend(stream.feed("response.output_text.delta", {"delta": "visible"}))
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 1,
                        "input_tokens_details": {
                            "cached_tokens": 15,
                            "cache_write_tokens": 3,
                        },
                    }
                }
            },
        )
    )

    message_delta = next(
        event
        for event in parse_sse_text("".join(output))
        if event.event == "message_delta"
    )
    assert message_delta.data["usage"] == {
        "input_tokens": 5,
        "output_tokens": 1,
        "cache_read_input_tokens": 15,
        "cache_creation_input_tokens": 3,
    }


def test_responses_provider_stream_ignores_impossible_cached_breakdown() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="openai/gpt-test",
        input_tokens=0,
    )
    output = stream.start()
    output.extend(stream.feed("response.output_text.delta", {"delta": "visible"}))
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "input_tokens_details": {"cached_tokens": 20},
                    }
                }
            },
        )
    )

    message_delta = next(
        event
        for event in parse_sse_text("".join(output))
        if event.event == "message_delta"
    )
    assert message_delta.data["usage"] == {
        "input_tokens": 10,
        "output_tokens": 1,
    }


def test_responses_provider_stream_maps_real_cache_write_counter() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="openai/gpt-test",
        input_tokens=0,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 1,
                        "input_tokens_details": {
                            "cached_tokens": 15,
                            "cache_write_tokens": 3,
                        },
                    }
                }
            },
        )
    )

    message_delta = next(
        event
        for event in parse_sse_text("".join(output))
        if event.event == "message_delta"
    )
    assert message_delta.data["usage"] == {
        "input_tokens": 5,
        "output_tokens": 1,
        "cache_read_input_tokens": 15,
        "cache_creation_input_tokens": 3,
    }


def test_responses_provider_stream_ignores_impossible_cached_breakdown() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="openai/gpt-test",
        input_tokens=0,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "input_tokens_details": {"cached_tokens": 20},
                    }
                }
            },
        )
    )

    message_delta = next(
        event
        for event in parse_sse_text("".join(output))
        if event.event == "message_delta"
    )
    assert message_delta.data["usage"] == {
        "input_tokens": 10,
        "output_tokens": 1,
    }


def test_responses_provider_stream_surfaces_failed_event() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="gpt-test",
        input_tokens=0,
    )

    with pytest.raises(ResponsesStreamFailure, match="capacity") as exc_info:
        stream.feed(
            "response.failed",
            {
                "response": {
                    "error": {
                        "code": "server_error",
                        "message": "No capacity",
                    }
                }
            },
        )

    assert exc_info.value.code == "server_error"


def test_responses_provider_stream_restores_added_and_done_only_tool_names() -> None:
    originals = (
        "mcp__responses_added__" + "x" * 70,
        "mcp__responses_done__" + "y" * 70,
    )
    codec = OpenAIToolNameCodec.from_names(originals)
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="gpt-test",
        input_tokens=0,
        tool_names=codec,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.output_item.added",
            {
                "item": {
                    "type": "function_call",
                    "id": "fc_added",
                    "call_id": "call_added",
                    "name": codec.encode(originals[0]),
                }
            },
        )
    )
    output.extend(
        stream.feed(
            "response.output_item.done",
            {
                "item": {
                    "type": "function_call",
                    "id": "fc_added",
                    "call_id": "call_added",
                    "name": codec.encode(originals[0]),
                    "arguments": "{}",
                }
            },
        )
    )
    output.extend(
        stream.feed(
            "response.output_item.done",
            {
                "item": {
                    "type": "function_call",
                    "id": "fc_done",
                    "call_id": "call_done",
                    "name": codec.encode(originals[1]),
                    "arguments": "{}",
                }
            },
        )
    )

    event_text = "".join(output)
    starts = [
        event.data["content_block"]
        for event in parse_sse_text(event_text)
        if event.event == "content_block_start"
    ]
    assert [start["name"] for start in starts] == list(originals)
    assert all(codec.encode(name) not in event_text for name in originals)
