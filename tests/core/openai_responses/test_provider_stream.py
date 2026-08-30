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
from free_claude_code.core.reasoning import ReasoningPolicy


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
        "input_tokens": 8,
        "output_tokens": 8,
        "cache_creation_input_tokens": 4,
    }
    # The provider's inclusive total is normalized into disjoint telemetry
    # buckets before the public receipt is governed by the request estimate.
    assert stream.usage_input_tokens == 1
    assert stream.usage_cache_read_tokens == 15


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


def test_responses_provider_stream_preserves_final_summary_and_deduplicates_snapshot() -> (
    None
):
    stream = ResponsesProviderStream(
        message_id="msg_summary_done",
        model="openai/gpt-5.6-luna",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.output_item.added",
            {"item": {"type": "reasoning", "id": "rs_done"}},
        )
    )
    output.extend(
        stream.feed(
            "response.reasoning_summary_text.delta",
            {
                "item_id": "rs_done",
                "summary_index": 0,
                "delta": "Luna summary",
            },
        )
    )
    output.extend(
        stream.feed(
            "response.reasoning_summary_text.done",
            {
                "item_id": "rs_done",
                "summary_index": 0,
                "text": "Luna summary",
            },
        )
    )
    output.extend(
        stream.feed(
            "response.output_item.done",
            {
                "item": {
                    "type": "reasoning",
                    "id": "rs_done",
                    "summary": [{"type": "summary_text", "text": "Luna summary"}],
                }
            },
        )
    )
    output.extend(
        stream.feed(
            "response.completed",
            {"response": {"usage": {"input_tokens": 1, "output_tokens": 3}}},
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == "Luna summary"
    assert stream.provider_visible_reasoning_summary is True
    assert stream.provider_visible_reasoning_summary_length == len("Luna summary")
    assert [
        event.data["delta"]["thinking"]
        for event in events
        if event.event == "content_block_delta"
        and event.data["delta"].get("type") == "thinking_delta"
    ] == ["Luna summary"]


def test_responses_provider_stream_preserves_summary_part_and_final_item_fallback() -> (
    None
):
    stream = ResponsesProviderStream(
        message_id="msg_summary_part",
        model="openai/gpt-5.6-luna",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.reasoning_summary_part.added",
            {
                "item_id": "rs_part",
                "output_index": 0,
                "summary_index": 0,
                "part": {"type": "summary_text", "text": "Luna "},
            },
        )
    )
    output.extend(
        stream.feed(
            "response.reasoning_summary_part.done",
            {
                "item_id": "rs_part",
                "output_index": 0,
                "summary_index": 0,
                "part": {"type": "summary_text", "text": "Luna summary"},
            },
        )
    )
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "output": [
                        {
                            "type": "reasoning",
                            "id": "rs_part",
                            "summary": [
                                {"type": "summary_text", "text": "Luna summary"}
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 3},
                }
            },
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == "Luna summary"
    assert stream.provider_visible_reasoning_summary is True
    assert stream.provider_visible_reasoning_summary_length == len("Luna summary")


def test_responses_provider_stream_preserves_summary_done_without_any_delta() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_summary_done_only",
        model="openai/gpt-5.6-luna",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.reasoning_summary_text.done",
            {
                "item_id": "rs_done_only",
                "summary_index": 0,
                "text": "Final Luna summary",
            },
        )
    )
    output.extend(
        stream.feed(
            "response.completed",
            {"response": {"usage": {"input_tokens": 1, "output_tokens": 3}}},
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == "Final Luna summary"
    assert stream.provider_visible_reasoning_summary is True
    assert stream.provider_visible_reasoning_summary_length == len("Final Luna summary")


def test_responses_provider_stream_reconciles_indexed_item_identity() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_indexed_identity",
        model="openai/gpt-5.6-luna",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.reasoning_summary_text.delta",
            {
                "output_index": 0,
                "summary_index": 0,
                "delta": "prefix",
            },
        )
    )
    output.extend(
        stream.feed(
            "response.output_item.done",
            {
                "output_index": 0,
                "item": {
                    "type": "reasoning",
                    "id": "rs_indexed",
                    "summary": [{"type": "summary_text", "text": "prefix and suffix"}],
                },
            },
        )
    )
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "output": [
                        {
                            "type": "reasoning",
                            "id": "rs_indexed",
                            "summary": [
                                {"type": "summary_text", "text": "prefix and suffix"}
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                }
            },
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == "prefix and suffix"


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
    assert stream.incomplete_reason == "novel_provider_reason"
    events = parse_sse_text("".join(output))
    message_delta = next(event for event in events if event.event == "message_delta")
    assert message_delta.data["delta"]["stop_reason"] == "end_turn"


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


def test_responses_provider_stream_recovers_text_from_terminal_output_snapshot() -> (
    None
):
    stream = ResponsesProviderStream(
        message_id="msg_terminal_text",
        model="openai/gpt-5.6-luna",
        input_tokens=2,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_item",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "terminal-only answer",
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 2, "output_tokens": 4},
                }
            },
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert "terminal-only answer" in "".join(
        event.data["delta"]["text"]
        for event in events
        if event.event == "content_block_delta"
        and event.data["delta"].get("type") == "text_delta"
    )


def test_responses_provider_stream_deduplicates_text_done_and_final_message() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_text_snapshot",
        model="openai/gpt-5.6-luna",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.output_text.delta",
            {
                "item_id": "msg_item",
                "output_index": 0,
                "content_index": 0,
                "delta": "prefix",
            },
        )
    )
    output.extend(
        stream.feed(
            "response.output_text.done",
            {
                "item_id": "msg_item",
                "output_index": 0,
                "content_index": 0,
                "text": "prefix and suffix",
            },
        )
    )
    output.extend(
        stream.feed(
            "response.output_item.done",
            {
                "output_index": 0,
                "item": {
                    "type": "message",
                    "id": "msg_item",
                    "content": [{"type": "output_text", "text": "prefix and suffix"}],
                },
            },
        )
    )
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_item",
                            "content": [
                                {"type": "output_text", "text": "prefix and suffix"}
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 3},
                }
            },
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert [
        event.data["delta"]["text"]
        for event in events
        if event.event == "content_block_delta"
        and event.data["delta"].get("type") == "text_delta"
    ] == ["prefix", " and suffix"]


def test_responses_provider_stream_preserves_refusal_from_stream_and_snapshot() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_refusal",
        model="openai/gpt-5.6-luna",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.refusal.delta",
            {
                "item_id": "msg_item",
                "output_index": 0,
                "content_index": 0,
                "delta": "I can't ",
            },
        )
    )
    output.extend(
        stream.feed(
            "response.refusal.done",
            {
                "item_id": "msg_item",
                "output_index": 0,
                "content_index": 0,
                "refusal": "I can't help with that.",
            },
        )
    )
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_item",
                            "content": [
                                {
                                    "type": "refusal",
                                    "refusal": "I can't help with that.",
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 4},
                }
            },
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert stream.provider_refusal is True
    assert stream.provider_refusal_length == len("I can't help with that.")
    assert "I can't help with that." in "".join(
        event.data["delta"]["text"]
        for event in events
        if event.event == "content_block_delta"
        and event.data["delta"].get("type") == "text_delta"
    )


def test_responses_provider_stream_hides_reasoning_when_explicitly_off() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_reasoning_off",
        model="openai/gpt-5.6-luna",
        input_tokens=1,
        reasoning=ReasoningPolicy.off(),
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.reasoning_summary_text.delta",
            {"item_id": "rs_off", "summary_index": 0, "delta": "hidden summary"},
        )
    )
    output.extend(
        stream.feed("response.output_text.delta", {"delta": "visible answer"})
    )
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                }
            },
        )
    )

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == ""
    assert "visible answer" in "".join(
        event.data["delta"]["text"]
        for event in events
        if event.event == "content_block_delta"
        and event.data["delta"].get("type") == "text_delta"
    )
    assert stream.provider_visible_reasoning_summary is True
    assert stream.harness_thinking_block is False


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
        "input_tokens": 2,
        "output_tokens": 1,
        "cache_read_input_tokens": 15,
        "cache_creation_input_tokens": 3,
    }


def test_responses_provider_stream_accepts_prompt_usage_cache_aliases() -> None:
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
                        "prompt_tokens": 30,
                        "output_tokens": 1,
                        "prompt_tokens_details": {
                            "cached_tokens": 20,
                            "prompt_cache_write_tokens": 4,
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
        "input_tokens": 6,
        "output_tokens": 1,
        "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 4,
    }


def test_responses_provider_stream_keeps_final_usage_at_governed_estimate() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="openai/gpt-test",
        input_tokens=12,
    )
    output = stream.start()
    output.extend(stream.feed("response.output_text.delta", {"delta": "visible"}))
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {
                        "input_tokens": 900,
                        "output_tokens": 1,
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
        "input_tokens": 12,
        "output_tokens": 1,
    }
    assert stream.usage_input_tokens == 900


def test_responses_provider_stream_partitions_cache_write_inside_estimate() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="openai/gpt-test",
        input_tokens=40,
    )
    output = stream.start()
    output.extend(stream.feed("response.output_text.delta", {"delta": "visible"}))
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {
                        "input_tokens": 40,
                        "output_tokens": 1,
                        "input_tokens_details": {
                            "cached_tokens": 31,
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
        "input_tokens": 6,
        "output_tokens": 1,
        "cache_read_input_tokens": 31,
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


def test_responses_provider_stream_ignores_cache_read_without_valid_total() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="openai/gpt-test",
        input_tokens=7,
    )
    output = stream.start()
    output.extend(stream.feed("response.output_text.delta", {"delta": "visible"}))
    output.extend(
        stream.feed(
            "response.completed",
            {
                "response": {
                    "usage": {
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
        "input_tokens": 7,
        "output_tokens": 1,
    }


def test_responses_provider_stream_ignores_negative_cache_counters() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="openai/gpt-test",
        input_tokens=7,
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
                        "input_tokens_details": {
                            "cached_tokens": -2,
                            "cache_write_tokens": -3,
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
        "input_tokens": 7,
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
