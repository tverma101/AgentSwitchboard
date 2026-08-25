from free_claude_code.core.openai_responses.provider_stream import (
    ResponsesProviderStream,
)


def test_duplicate_function_call_id_is_emitted_only_once() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_duplicate_item",
        model="muse-spark-1.2-contributor",
        input_tokens=0,
    )

    assert (
        stream.feed(
            "response.output_item.added",
            {
                "item": {
                    "type": "function_call",
                    "id": "fc_primary",
                    "call_id": "call_shared",
                    "name": "lookup",
                }
            },
        )
        == []
    )
    assert (
        stream.feed(
            "response.output_item.added",
            {
                "item": {
                    "type": "function_call",
                    "id": "fc_duplicate",
                    "call_id": "call_shared",
                    "name": "lookup",
                }
            },
        )
        == []
    )

    primary_done = stream.feed(
        "response.output_item.done",
        {
            "item": {
                "type": "function_call",
                "id": "fc_primary",
                "call_id": "call_shared",
                "name": "lookup",
                "arguments": "{}",
            }
        },
    )
    duplicate_done = stream.feed(
        "response.output_item.done",
        {
            "item": {
                "type": "function_call",
                "id": "fc_duplicate",
                "call_id": "call_shared",
                "name": "lookup",
                "arguments": "{}",
            }
        },
    )

    assert primary_done
    assert duplicate_done == []
    assert stream.tool_call_count == 1
    assert stream.complete_tool_calls is True
    assert stream.valid_tool_json is True
