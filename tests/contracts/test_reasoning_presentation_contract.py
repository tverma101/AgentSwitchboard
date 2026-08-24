"""Synthetic zero-provider contracts for Responses reasoning presentation."""

from free_claude_code.core.anthropic.stream_contracts import (
    assert_anthropic_stream_contract,
    parse_sse_text,
    text_content,
    thinking_content,
)
from free_claude_code.core.openai_responses.provider_stream import ResponsesProviderStream


def _complete(stream: ResponsesProviderStream, *, output_tokens: int = 2) -> list[str]:
    return stream.feed(
        "response.completed",
        {
            "response": {
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": output_tokens,
                }
            }
        },
    )


def test_visible_provider_summary_maps_to_anthropic_thinking() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_visible_summary",
        model="synthetic-model",
        input_tokens=1,
    )
    output = stream.start()
    output.extend(
        stream.feed(
            "response.output_item.added",
            {"item": {"type": "reasoning", "id": "rs_summary"}},
        )
    )
    output.extend(
        stream.feed(
            "response.reasoning_summary_text.delta",
            {"item_id": "rs_summary", "delta": "visible summary"},
        )
    )
    output.extend(stream.feed("response.output_text.delta", {"delta": "answer"}))
    output.extend(_complete(stream))

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == "visible summary"
    assert text_content(events) == "answer"
    assert stream.provider_visible_reasoning_summary is True
    assert stream.provider_opaque_reasoning is False
    assert stream.harness_thinking_block is True
    assert stream.harness_thinking_delta is True


def test_opaque_reasoning_never_fabricates_visible_summary() -> None:
    opaque = "opaque-continuation-token"
    stream = ResponsesProviderStream(
        message_id="msg_opaque_reasoning",
        model="synthetic-model",
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
                    "encrypted_content": opaque,
                }
            },
        )
    )
    output.extend(stream.feed("response.output_text.delta", {"delta": "answer"}))
    output.extend(_complete(stream))

    events = parse_sse_text("".join(output))
    assert_anthropic_stream_contract(events)
    assert thinking_content(events) == ""
    assert text_content(events) == "answer"
    assert stream.provider_visible_reasoning_summary is False
    assert stream.provider_opaque_reasoning is True
    assert stream.harness_thinking_block is True
    assert stream.harness_thinking_delta is False

    starts = [
        event.data["content_block"]
        for event in events
        if event.event == "content_block_start"
    ]
    assert {"type": "redacted_thinking", "data": opaque} in starts
    assert not any(
        event.data.get("delta", {}).get("type") == "thinking_delta"
        for event in events
        if event.event == "content_block_delta"
    )
