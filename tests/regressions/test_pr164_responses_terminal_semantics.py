import pytest

from free_claude_code.core.openai_responses import (
    ResponsesProviderStream,
    ResponsesStreamFailure,
)


def _stream() -> ResponsesProviderStream:
    return ResponsesProviderStream(
        message_id="msg_pr164",
        model="openai/gpt-test",
        input_tokens=1,
    )


def test_unknown_incomplete_reason_fails_instead_of_fabricating_end_turn() -> None:
    stream = _stream()
    stream.start()
    stream.feed(
        "response.output_text.delta",
        {
            "item_id": "msg_item",
            "output_index": 0,
            "content_index": 0,
            "delta": "partial answer",
        },
    )

    with pytest.raises(ResponsesStreamFailure) as caught:
        stream.feed(
            "response.incomplete",
            {
                "response": {
                    "incomplete_details": {"reason": "novel_provider_reason"},
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                }
            },
        )

    assert caught.value.code == "incomplete_response"
    assert stream.completed is False


def test_divergent_text_done_snapshot_fails_before_duplicate_output() -> None:
    stream = _stream()
    stream.start()
    stream.feed(
        "response.output_text.delta",
        {
            "item_id": "msg_item",
            "output_index": 0,
            "content_index": 0,
            "delta": "already streamed",
        },
    )

    with pytest.raises(ResponsesStreamFailure) as caught:
        stream.feed(
            "response.output_text.done",
            {
                "item_id": "msg_item",
                "output_index": 0,
                "content_index": 0,
                "text": "different replacement",
            },
        )

    assert caught.value.code == "divergent_terminal_snapshot"


def test_divergent_reasoning_done_snapshot_fails_before_duplicate_output() -> None:
    stream = _stream()
    stream.start()
    stream.feed(
        "response.reasoning_summary_text.delta",
        {
            "item_id": "rs_item",
            "output_index": 0,
            "summary_index": 0,
            "delta": "streamed reasoning",
        },
    )

    with pytest.raises(ResponsesStreamFailure) as caught:
        stream.feed(
            "response.reasoning_summary_text.done",
            {
                "item_id": "rs_item",
                "output_index": 0,
                "summary_index": 0,
                "text": "replacement reasoning",
            },
        )

    assert caught.value.code == "divergent_terminal_snapshot"


def test_append_only_terminal_snapshot_still_emits_only_missing_suffix() -> None:
    stream = _stream()
    stream.start()
    stream.feed(
        "response.output_text.delta",
        {
            "item_id": "msg_item",
            "output_index": 0,
            "content_index": 0,
            "delta": "prefix",
        },
    )

    events = stream.feed(
        "response.output_text.done",
        {
            "item_id": "msg_item",
            "output_index": 0,
            "content_index": 0,
            "text": "prefix and suffix",
        },
    )

    assert any(" and suffix" in event for event in events)
    assert all("prefix and suffix" not in event for event in events)
