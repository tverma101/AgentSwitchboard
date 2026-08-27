import json
from urllib.parse import urlsplit

import httpx
import pytest

from free_claude_code.cli.claude_env import build_claude_proxy_env
from free_claude_code.core.anthropic.stream_contracts import (
    assert_anthropic_stream_contract,
    parse_sse_text,
    text_content,
    thinking_content,
)
from smoke.lib.synthetic_gateway import (
    SyntheticAnthropicGateway,
    SyntheticThinkingFixture,
    fixture_names,
)


@pytest.mark.parametrize("fixture", tuple(SyntheticThinkingFixture))
def test_synthetic_gateway_serves_every_fixture_without_external_network(
    fixture: SyntheticThinkingFixture,
) -> None:
    with SyntheticAnthropicGateway(fixture) as gateway:
        response = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [{"role": "user", "content": "secret prompt"}],
            },
            timeout=5,
        )

    assert response.status_code == 200
    assert "message_start" in response.text
    events = parse_sse_text(response.text)
    if fixture is not SyntheticThinkingFixture.UNKNOWN_DELTA:
        assert_anthropic_stream_contract(events)
    if fixture is SyntheticThinkingFixture.REDACTED_THINKING:
        assert [
            event.data["content_block"]
            for event in events
            if event.event == "content_block_start"
        ] == [{"type": "redacted_thinking", "data": "opaque"}]
        assert not any(event.event == "content_block_delta" for event in events)
    elif fixture is SyntheticThinkingFixture.EMPTY_THINKING:
        assert [
            event.data["content_block"]
            for event in events
            if event.event == "content_block_start"
        ] == [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": ""},
        ]
        assert [
            event.data["delta"]
            for event in events
            if event.event == "content_block_delta"
        ] == [
            {
                "type": "text_delta",
                "text": "SYNTHETIC_EMPTY_THINKING_OK",
            }
        ]
    elif fixture is SyntheticThinkingFixture.EMPTY_THINKING_SIGNATURE:
        assert [
            event.data["content_block"]["type"]
            for event in events
            if event.event == "content_block_start"
        ] == ["thinking", "text"]
        assert [
            event.data["delta"]["type"]
            for event in events
            if event.event == "content_block_delta"
        ] == ["signature_delta", "text_delta"]
        assert thinking_content(events) == ""
    elif fixture is SyntheticThinkingFixture.USAGE_ONLY:
        assert [
            event.data["content_block"]
            for event in events
            if event.event == "content_block_start"
        ] == [{"type": "text", "text": ""}]
        assert not any(event.event == "content_block_delta" for event in events)
        message_delta = next(
            event for event in events if event.event == "message_delta"
        )
        assert message_delta.data["usage"] == {"input_tokens": 3, "output_tokens": 7}
        assert text_content(events) == thinking_content(events) == ""
    elif fixture is SyntheticThinkingFixture.UNSUPPORTED_THINKING:
        assert [
            event.data["content_block"]["type"]
            for event in events
            if event.event == "content_block_start"
        ] == ["text"]
        assert text_content(events) == "SYNTHETIC_UNSUPPORTED_THINKING_OK"
        assert thinking_content(events) == ""
    elif fixture is SyntheticThinkingFixture.VISIBLE_SUMMARY:
        assert [
            event.data["content_block"]["type"]
            for event in events
            if event.event == "content_block_start"
        ] == ["thinking", "text"]
        assert thinking_content(events) == "synthetic visible summary"
        assert text_content(events) == "SYNTHETIC_SUMMARY_OK"
    elif fixture is SyntheticThinkingFixture.OPAQUE_TOOL_ROUNDTRIP:
        assert "redacted_thinking" in response.text
    elif fixture in {
        SyntheticThinkingFixture.TOOL_ROUNDTRIP,
        SyntheticThinkingFixture.CONTEXT_GOVERNOR,
    }:
        assert "tool_use" in response.text
    else:
        assert "content_block_start" in response.text


def test_synthetic_gateway_tool_fixture_records_structural_continuation_only() -> None:
    with SyntheticAnthropicGateway(SyntheticThinkingFixture.TOOL_ROUNDTRIP) as gateway:
        first = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [{"role": "user", "content": "secret prompt"}],
                "tools": [{"name": "Read"}],
            },
            timeout=5,
        )
        second = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [
                    {"role": "user", "content": "secret prompt"},
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu_synthetic_read",
                                "name": "Read",
                                "input": {},
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_synthetic_read",
                                "content": "secret tool output",
                            }
                        ],
                    },
                ],
            },
            timeout=5,
        )
        receipts = gateway.request_receipts()

    assert first.status_code == second.status_code == 200
    assert "tool_use" in first.text
    assert "SYNTHETIC_TOOL_CONTINUATION" in second.text
    assert len(receipts) == 2
    assert receipts[0]["tool_result_seen"] is False
    assert receipts[0]["tools_declared"] is True
    assert receipts[1]["tool_result_seen"] is True
    assert receipts[1]["content_block_types"] == ["tool_use", "tool_result"]
    assert receipts[1]["thinking_history_seen"] is False
    assert "secret" not in json.dumps(receipts)


def test_synthetic_gateway_opaque_tool_fixture_preserves_ordered_state_receipt() -> (
    None
):
    with SyntheticAnthropicGateway(
        SyntheticThinkingFixture.OPAQUE_TOOL_ROUNDTRIP
    ) as gateway:
        first = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [{"role": "user", "content": "secret prompt"}],
                "tools": [{"name": "Read"}],
            },
            timeout=5,
        )
        second = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [
                    {"role": "user", "content": "secret prompt"},
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "redacted_thinking", "data": "opaque"},
                            {
                                "type": "tool_use",
                                "id": "toolu_synthetic_read",
                                "name": "Read",
                                "input": {},
                            },
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_synthetic_read",
                                "content": "secret tool output",
                            }
                        ],
                    },
                ],
            },
            timeout=5,
        )
        receipts = gateway.request_receipts()

    first_events = parse_sse_text(first.text)
    assert_anthropic_stream_contract(first_events)
    assert [
        event.data["content_block"]
        for event in first_events
        if event.event == "content_block_start"
    ] == [
        {"type": "redacted_thinking", "data": "opaque"},
        {
            "type": "tool_use",
            "id": "toolu_synthetic_read",
            "name": "Read",
            "input": {},
        },
    ]
    assert "SYNTHETIC_TOOL_CONTINUATION" in second.text
    assert len(receipts) == 2
    assert receipts[0]["content_block_types"] == []
    assert receipts[1]["content_block_types"] == [
        "redacted_thinking",
        "tool_use",
        "tool_result",
    ]
    assert receipts[1]["thinking_history_seen"] is True
    assert receipts[1]["tool_result_seen"] is True
    assert receipts[1]["tool_result_bytes"] == len("secret tool output")
    assert (
        isinstance(receipts[1]["request_bytes"], int)
        and isinstance(receipts[0]["request_bytes"], int)
        and receipts[1]["request_bytes"] > receipts[0]["request_bytes"]
    )
    assert "secret" not in json.dumps(receipts)


def test_context_governor_fixture_records_only_numeric_size_evidence() -> None:
    with SyntheticAnthropicGateway(
        SyntheticThinkingFixture.CONTEXT_GOVERNOR
    ) as gateway:
        first = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [{"role": "user", "content": "secret prompt"}],
                "tools": [{"name": "Bash"}],
            },
            timeout=5,
        )
        second = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [
                    {"role": "user", "content": "secret prompt"},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_synthetic_bash",
                                "content": "secret tool output",
                            }
                        ],
                    },
                ],
            },
            timeout=5,
        )
        receipts = gateway.request_receipts()

    assert first.status_code == second.status_code == 200
    assert "tool_use" in first.text
    assert "SYNTHETIC_CONTEXT_GOVERNOR_OK" in second.text
    assert receipts[1]["tool_result_bytes"] == len("secret tool output")
    assert receipts[1]["tool_result_lines"] == 1
    assert "secret" not in json.dumps(receipts)


@pytest.mark.parametrize(
    ("fixture", "first_blocks"),
    (
        pytest.param(
            SyntheticThinkingFixture.THINKING_TOOL_ROUNDTRIP,
            ["thinking", "tool_use"],
            id="thinking-tool",
        ),
        pytest.param(
            SyntheticThinkingFixture.INTERLEAVED_TOOL_ROUNDTRIP,
            ["thinking", "tool_use", "thinking"],
            id="interleaved-thinking-tool",
        ),
    ),
)
def test_synthetic_gateway_thinking_tool_roundtrip_is_structural(
    fixture: SyntheticThinkingFixture,
    first_blocks: list[str],
) -> None:
    assistant_blocks = [
        (
            {
                "type": "tool_use",
                "id": "toolu_synthetic_read",
                "name": "Read",
                "input": {},
            }
            if block_type == "tool_use"
            else {"type": "thinking", "thinking": "synthetic"}
        )
        for block_type in first_blocks
    ]
    with SyntheticAnthropicGateway(fixture) as gateway:
        first = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [{"role": "user", "content": "secret prompt"}],
                "tools": [{"name": "Read"}],
            },
            timeout=5,
        )
        second = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [
                    {"role": "user", "content": "secret prompt"},
                    {
                        "role": "assistant",
                        "content": assistant_blocks,
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_synthetic_read",
                                "content": "secret tool output",
                            }
                        ],
                    },
                ],
            },
            timeout=5,
        )
        receipts = gateway.request_receipts()

    first_events = parse_sse_text(first.text)
    assert_anthropic_stream_contract(first_events)
    assert [
        event.data["content_block"]["type"]
        for event in first_events
        if event.event == "content_block_start"
    ] == first_blocks
    assert second.status_code == 200
    assert "SYNTHETIC_TOOL_CONTINUATION" in second.text
    assert receipts[1]["content_block_types"] == [
        *first_blocks,
        "tool_result",
    ]
    assert receipts[1]["thinking_history_seen"] is True
    assert receipts[1]["tool_result_seen"] is True
    assert "secret" not in json.dumps(receipts)


def test_synthetic_gateway_summary_thinking_and_opaque_shapes_are_distinct() -> None:
    observed: dict[str, tuple[list[str], str, str]] = {}
    for fixture in (
        SyntheticThinkingFixture.VISIBLE_SUMMARY,
        SyntheticThinkingFixture.VISIBLE_THINKING,
        SyntheticThinkingFixture.REDACTED_THINKING,
    ):
        with SyntheticAnthropicGateway(fixture) as gateway:
            response = httpx.post(
                f"{gateway.base_url}/messages",
                json={
                    "model": "minimax-m2.7",
                    "messages": [{"role": "user", "content": "secret prompt"}],
                },
                timeout=5,
            )
        events = parse_sse_text(response.text)
        observed[fixture.value] = (
            [
                event.data["content_block"]["type"]
                for event in events
                if event.event == "content_block_start"
            ],
            thinking_content(events),
            text_content(events),
        )

    assert observed["visible_summary"][0] == ["thinking", "text"]
    assert observed["visible_thinking"][0] == ["thinking", "text"]
    assert observed["visible_summary"][1] != observed["visible_thinking"][1]
    assert observed["redacted_thinking"] == (["redacted_thinking"], "", "")


def test_synthetic_gateway_claude_env_cannot_escape_to_anthropic() -> None:
    with SyntheticAnthropicGateway() as gateway:
        parts = urlsplit(gateway.base_url)
        env = build_claude_proxy_env(
            proxy_root_url=gateway.base_url,
            auth_token="synthetic-local-token",
            base_env={
                "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                "ANTHROPIC_API_URL": "https://api.anthropic.com/v1",
                "ANTHROPIC_API_KEY": "synthetic-secret",
            },
        )

    assert parts.scheme == "http"
    assert parts.hostname == "127.0.0.1"
    assert env["ANTHROPIC_BASE_URL"] == gateway.base_url
    assert env["ANTHROPIC_AUTH_TOKEN"] == "synthetic-local-token"
    assert "ANTHROPIC_API_URL" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "api.anthropic.com" not in json.dumps(env)


def test_synthetic_fixture_names_are_stable_and_complete() -> None:
    assert fixture_names() == tuple(
        fixture.value for fixture in SyntheticThinkingFixture
    )
