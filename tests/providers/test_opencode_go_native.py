"""Contracts for OpenCode Go native protocol routing."""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx
import pytest

from free_claude_code.application.errors import InvalidRequestError
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.anthropic.openai_tool_names import OpenAIToolNameCodec
from free_claude_code.core.anthropic.stream_contracts import (
    assert_anthropic_stream_contract,
    parse_sse_text,
    thinking_content,
)
from free_claude_code.core.fault_attribution import (
    AttemptEvidence,
    FaultConfidence,
    FaultDomain,
)
from free_claude_code.core.reasoning import (
    DEFAULT_REASONING_POLICY,
    ReasoningEffort,
    ReasoningPolicy,
)
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.opencode_go import (
    GO_MODEL_PROTOCOLS,
    GoProtocol,
    OpenCodeGoProvider,
    build_native_messages_body,
    protocol_for_model,
)
from free_claude_code.providers.opencode_go.provider import (
    _record_failure,
    _sse_chunk_has_output,
    _sse_event_types,
)

_PNG_DATA = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _ResponsesEvent:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str, exclude_none: bool) -> dict[str, object]:
        del mode, exclude_none
        return self._payload


class _ResponsesStream:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = iter(_ResponsesEvent(event) for event in events)
        self.closed = False

    def __aiter__(self) -> AsyncIterator[_ResponsesEvent]:
        return self

    async def __anext__(self) -> _ResponsesEvent:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True


class _FailingResponsesStream:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.closed = False

    def __aiter__(self) -> AsyncIterator[_ResponsesEvent]:
        return self

    async def __anext__(self) -> _ResponsesEvent:
        raise self._error

    async def aclose(self) -> None:
        self.closed = True


def _provider_request(model: str) -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": model,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hello"}],
        }
    )


def _upstream_request(url: str) -> httpx.Request:
    return httpx.Request("POST", url)


def test_go_protocol_manifest_matches_documented_2026_09_02_split() -> None:
    responses = {
        model
        for model, protocol in GO_MODEL_PROTOCOLS.items()
        if protocol is GoProtocol.RESPONSES
    }
    messages = {
        model
        for model, protocol in GO_MODEL_PROTOCOLS.items()
        if protocol is GoProtocol.MESSAGES
    }
    chat = {
        model
        for model, protocol in GO_MODEL_PROTOCOLS.items()
        if protocol is GoProtocol.CHAT
    }

    assert responses == {
        "grok-4.6",
        "grok-4.5",
        "gpt-5.6-luna",
        "muse-spark-1.3-contributor",
        "muse-spark-1.2-contributor",
    }
    assert messages == {
        "minimax-m3",
        "minimax-m2.7",
        "minimax-m2.5",
        "qwen3.8-max",
        "qwen3.8-flash",
        "qwen3.7-max",
        "qwen3.7-plus",
        "qwen3.6-plus",
    }
    assert chat == {
        "glm-5.3-flash",
        "glm-5.3",
        "glm-5.2",
        "glm-5.1",
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.6",
        "longcat-2.0",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
        "mimo-v2.5",
        "mimo-v2.5-pro",
        "hy4-preview",
        "hy3",
        "ox-alpha-free",
    }
    assert len(GO_MODEL_PROTOCOLS) == 29


def test_unknown_go_model_fails_closed_without_protocol_probe() -> None:
    with pytest.raises(InvalidRequestError, match="protocol is unknown"):
        protocol_for_model("future-model-not-in-manifest")


def test_explicit_provider_http_status_is_classified_without_guessing_transport() -> (
    None
):
    class AuthenticationProbeError(Exception):
        status_code = 401

    evidence = AttemptEvidence(
        turn_id="turn_auth",
        request_id="req_auth",
        protocol="responses",
        provider="OPENCODE_GO",
        model="muse-spark-1.2-contributor",
        attempt_number=1,
    )

    _record_failure(evidence, AuthenticationProbeError())

    assert evidence.http_status == 401
    assert evidence.fault_domain is FaultDomain.OPENCODE_GATEWAY
    assert evidence.confidence is FaultConfidence.HIGH
    assert evidence.evidence_codes == ["upstream_error:http_401"]


def test_native_messages_preserve_anthropic_cache_control_and_images() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "qwen3.7-plus",
            "max_tokens": 4096,
            "system": [
                {
                    "type": "text",
                    "text": "stable system prefix",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
                            },
                        },
                        {
                            "type": "text",
                            "text": "inspect this",
                            "cache_control": {"type": "ephemeral"},
                        },
                    ],
                }
            ],
            "tools": [
                {
                    "name": "Read",
                    "description": "Read a file",
                    "input_schema": {"type": "object"},
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    )

    body = build_native_messages_body(request)

    assert body["stream"] is True
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert (
        body["messages"][0]["content"][0]["source"]["data"]
        == "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    assert body["messages"][0]["content"][1]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][0]["cache_control"] == {"type": "ephemeral"}


def test_native_messages_reject_cross_protocol_extra_body() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "qwen3.7-plus",
            "messages": [{"role": "user", "content": "hi"}],
            "extra_body": {"cache_control": {"type": "ephemeral"}},
        }
    )

    with pytest.raises(InvalidRequestError, match="extra_body"):
        build_native_messages_body(request)


def test_responses_conversion_shortens_long_tool_names_for_muse() -> None:
    long_name = "mcp__very_long_namespace__" + "tool_component_" * 6
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": "use the tool"}],
            "tools": [
                {
                    "name": long_name,
                    "description": "Test tool",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        }
    )

    body = OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=DEFAULT_REASONING_POLICY,
    )

    wire_name = body["tools"][0]["name"]
    assert wire_name != long_name
    assert len(wire_name) <= 64


def test_responses_body_keeps_session_identity_metadata_only_and_deterministic() -> (
    None
):
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "messages": [{"role": "user", "content": "hello"}],
            "claude_session_id": "session-stable",
            "metadata": {"timestamp": "2026-08-24T12:00:00Z"},
        }
    )

    first = OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=DEFAULT_REASONING_POLICY,
    )
    second = OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=DEFAULT_REASONING_POLICY,
    )

    assert first == second
    assert first["prompt_cache_key"] == "session-stable"
    assert first["input"][0]["content"][0]["text"] == "hello"
    assert "session_id" not in first["metadata"]


def test_responses_body_rejects_turn_identity_as_cache_key() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "messages": [{"role": "user", "content": "hello"}],
            "claude_session_id": "turn-123456",
        }
    )

    body = OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=DEFAULT_REASONING_POLICY,
    )

    assert "prompt_cache_key" not in body


@pytest.mark.parametrize(
    "tool_choice",
    [
        {"type": "tool", "name": "Read"},
        {"type": "any"},
        {"type": "none"},
    ],
)
def test_muse_rejects_unsupported_tool_choice_before_provider_call(
    tool_choice: dict[str, str],
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "messages": [{"role": "user", "content": "use a tool"}],
            "tools": [
                {
                    "name": "Read",
                    "description": "Read a file",
                    "input_schema": {"type": "object"},
                }
            ],
            "tool_choice": tool_choice,
        }
    )

    with pytest.raises(InvalidRequestError, match=r"accepts only.*auto"):
        OpenCodeGoProvider._build_responses_body(
            request,
            reasoning=DEFAULT_REASONING_POLICY,
        )


def test_muse_tool_aliases_cover_exact_limit_and_collision_shapes() -> None:
    originals = (
        "a" * 64,
        "b" * 65,
        "collision_prefix_" + "x" * 80 + "a",
        "collision_prefix_" + "x" * 80 + "b",
    )
    codec = OpenAIToolNameCodec.from_names(originals)
    aliases = tuple(codec.encode(name) for name in originals)

    assert all(len(alias) <= 64 for alias in aliases)
    assert len(set(aliases)) == len(originals)
    assert tuple(codec.decode(alias) for alias in aliases) == originals


@pytest.mark.parametrize(
    ("effort", "expected_reasoning"),
    [
        (ReasoningEffort.MINIMAL, {"effort": "minimal", "summary": "auto"}),
        (ReasoningEffort.LOW, {"effort": "low", "summary": "auto"}),
        (ReasoningEffort.MEDIUM, {"effort": "medium", "summary": "auto"}),
        (ReasoningEffort.HIGH, {"effort": "high", "summary": "auto"}),
        (ReasoningEffort.XHIGH, {"effort": "xhigh", "summary": "auto"}),
        # OpenCode Go's Responses endpoint has no `max` variant; the provider
        # adapter sends its highest representable effort.
        (ReasoningEffort.MAX, {"effort": "xhigh", "summary": "auto"}),
    ],
)
def test_muse_responses_body_translates_each_reasoning_effort(
    effort: ReasoningEffort, expected_reasoning: dict[str, str]
) -> None:
    """The outgoing /responses body names the exact client-selected effort."""
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": "reason about this"}],
        }
    )

    body = OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=ReasoningPolicy.on(effort=effort),
    )

    assert body["model"] == "muse-spark-1.2-contributor"
    assert body["reasoning"] == expected_reasoning


def test_muse_responses_body_maps_off_to_lowest_supported_effort() -> None:
    """Reasoning off suppresses output while using Muse's lowest effort."""
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": "no reasoning"}],
        }
    )

    body = OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=ReasoningPolicy.off(),
    )

    assert body["reasoning"] == {"effort": "minimal", "summary": "auto"}


@pytest.mark.asyncio
async def test_native_protocols_share_one_hardened_transport_pool() -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid",
            max_concurrency=2,
        ),
        admission=ProviderAdmissionController(provider_name="OPENCODE_GO"),
    )
    try:
        assert provider._native_http._trust_env is False
        assert provider._native_http.follow_redirects is False
        assert provider._responses._client is provider._native_http
    finally:
        await provider.cleanup()


@pytest.mark.asyncio
async def test_responses_stream_retries_pre_payload_transient_status() -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_attempts=2,
            base_delay=0,
            jitter=0,
        ),
    )
    request = _provider_request("muse-spark-1.2-contributor")
    upstream_request = _upstream_request("https://example.invalid/v1/responses")
    retry_response = httpx.Response(
        503,
        request=upstream_request,
        text="temporarily unavailable",
    )
    retry_error = httpx.HTTPStatusError(
        "temporarily unavailable",
        request=upstream_request,
        response=retry_response,
    )
    provider._responses.responses.create = AsyncMock(
        side_effect=[
            retry_error,
            _ResponsesStream(
                [
                    {"type": "response.output_text.delta", "delta": "ok"},
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_1",
                            "usage": {"input_tokens": 3, "output_tokens": 1},
                        },
                    },
                ]
            ),
        ]
    )

    try:
        events = [
            event
            async for event in provider.stream_response(
                request,
                request_id="req_retry",
            )
        ]
    finally:
        await provider.cleanup()

    assert provider._responses.responses.create.await_count == 2
    assert any("ok" in event for event in events)


@pytest.mark.asyncio
async def test_responses_stream_retries_before_commit_when_iterator_cuts_off() -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_attempts=2,
            base_delay=0,
            jitter=0,
        ),
    )
    first_stream = _FailingResponsesStream(httpx.ReadError("connection closed"))
    provider._responses.responses.create = AsyncMock(
        side_effect=[
            first_stream,
            _ResponsesStream(
                [
                    {"type": "response.output_text.delta", "delta": "ok"},
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_after_cutoff",
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        },
                    },
                ]
            ),
        ]
    )

    try:
        events = [
            event
            async for event in provider.stream_response(
                _provider_request("gpt-5.6-luna"),
                request_id="req_iterator_cutoff",
            )
        ]
    finally:
        await provider.cleanup()

    assert provider._responses.responses.create.await_count == 2
    assert first_stream.closed is True
    parsed = parse_sse_text("".join(events))
    assert_anthropic_stream_contract(parsed)
    assert "ok" in "".join(
        event.data["delta"]["text"]
        for event in parsed
        if event.event == "content_block_delta"
        and event.data["delta"].get("type") == "text_delta"
    )


@pytest.mark.asyncio
async def test_responses_stream_retries_when_iterator_ends_without_terminal() -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_attempts=2,
            base_delay=0,
            jitter=0,
        ),
    )
    first_stream = _ResponsesStream(
        [{"type": "response.output_text.delta", "delta": "partial"}]
    )
    provider._responses.responses.create = AsyncMock(
        side_effect=[
            first_stream,
            _ResponsesStream(
                [
                    {"type": "response.output_text.delta", "delta": "complete"},
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_after_eof",
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        },
                    },
                ]
            ),
        ]
    )

    try:
        events = [
            event
            async for event in provider.stream_response(
                _provider_request("gpt-5.6-luna"),
                request_id="req_iterator_eof",
            )
        ]
    finally:
        await provider.cleanup()

    assert provider._responses.responses.create.await_count == 2
    assert first_stream.closed is True
    parsed = parse_sse_text("".join(events))
    assert_anthropic_stream_contract(parsed)
    text = "".join(
        event.data["delta"]["text"]
        for event in parsed
        if event.event == "content_block_delta"
        and event.data["delta"].get("type") == "text_delta"
    )
    assert text == "complete"


@pytest.mark.asyncio
async def test_luna_responses_stream_hides_reasoning_when_explicitly_off() -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_attempts=1,
            base_delay=0,
            jitter=0,
        ),
    )
    provider._responses.responses.create = AsyncMock(
        return_value=_ResponsesStream(
            [
                {
                    "type": "response.reasoning_summary_text.delta",
                    "item_id": "rs_off",
                    "summary_index": 0,
                    "delta": "hidden reasoning",
                },
                {"type": "response.output_text.delta", "delta": "visible answer"},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_off",
                        "usage": {"input_tokens": 1, "output_tokens": 2},
                    },
                },
            ]
        )
    )

    try:
        events = [
            event
            async for event in provider.stream_response(
                _provider_request("gpt-5.6-luna"),
                request_id="req_reasoning_off",
                reasoning=ReasoningPolicy.off(),
            )
        ]
    finally:
        await provider.cleanup()

    parsed = parse_sse_text("".join(events))
    assert_anthropic_stream_contract(parsed)
    assert thinking_content(parsed) == ""
    assert "visible answer" in "".join(
        event.data["delta"]["text"]
        for event in parsed
        if event.event == "content_block_delta"
        and event.data["delta"].get("type") == "text_delta"
    )
    request_kwargs = provider._responses.responses.create.call_args.kwargs
    assert request_kwargs["reasoning"] == {"effort": "minimal", "summary": "auto"}


@pytest.mark.asyncio
async def test_luna_responses_stream_preserves_final_reasoning_summary() -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_attempts=1,
            base_delay=0,
            jitter=0,
        ),
    )
    provider._responses.responses.create = AsyncMock(
        return_value=_ResponsesStream(
            [
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {"type": "reasoning", "id": "rs_luna"},
                },
                {
                    "type": "response.reasoning_summary_text.done",
                    "item_id": "rs_luna",
                    "output_index": 0,
                    "summary_index": 0,
                    "text": "Luna final summary",
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "type": "reasoning",
                        "id": "rs_luna",
                        "summary": [
                            {"type": "summary_text", "text": "Luna final summary"}
                        ],
                    },
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_luna_summary",
                        "output": [
                            {
                                "type": "reasoning",
                                "id": "rs_luna",
                                "summary": [
                                    {
                                        "type": "summary_text",
                                        "text": "Luna final summary",
                                    }
                                ],
                            }
                        ],
                        "usage": {"input_tokens": 3, "output_tokens": 4},
                    },
                },
            ]
        )
    )
    try:
        events = [
            event
            async for event in provider.stream_response(
                _provider_request("gpt-5.6-luna"),
                request_id="req_luna_summary",
            )
        ]
    finally:
        await provider.cleanup()

    parsed = parse_sse_text("".join(events))
    assert_anthropic_stream_contract(parsed)
    assert thinking_content(parsed) == "Luna final summary"
    assert [
        event.data["delta"]["thinking"]
        for event in parsed
        if event.event == "content_block_delta"
        and event.data["delta"].get("type") == "thinking_delta"
    ] == ["Luna final summary"]


@pytest.mark.asyncio
async def test_responses_receipt_records_metadata_only_timing(monkeypatch) -> None:
    payload_marker = "unique-output-payload-should-not-be-retained"
    receipts: list[dict[str, object]] = []

    def record_trace(**fields: object) -> None:
        if fields.get("event") == "provider.fault_attribution":
            receipts.append(fields)

    monkeypatch.setattr(
        "free_claude_code.providers.opencode_go.provider.trace_event",
        record_trace,
    )
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_attempts=1,
            base_delay=0,
            jitter=0,
        ),
    )
    provider._responses.responses.create = AsyncMock(
        return_value=_ResponsesStream(
            [
                {"type": "response.output_text.delta", "delta": payload_marker},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_timing",
                        "usage": {"input_tokens": 3, "output_tokens": 1},
                    },
                },
            ]
        )
    )
    request = MessagesRequest.model_validate(
        {
            "model": "muse-spark-1.2-contributor",
            "max_tokens": 32,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "inspect this"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": _PNG_DATA,
                            },
                        },
                    ],
                }
            ],
        }
    )

    try:
        events = [
            event
            async for event in provider.stream_response(
                request,
                request_id="req_timing",
            )
        ]
    finally:
        await provider.cleanup()

    assert any(payload_marker in event for event in events)
    assert len(receipts) == 1
    receipt = receipts[0]
    assert type(receipt["duration_ms"]) is int
    assert type(receipt["time_to_first_token_ms"]) is int
    assert receipt["duration_ms"] >= receipt["time_to_first_token_ms"]
    assert receipt["media_count"] == 1
    assert type(receipt["media_type_hash"]) is str
    serialized = json.dumps(receipt)
    assert "hello" not in serialized
    assert payload_marker not in serialized


@pytest.mark.asyncio
async def test_messages_receipt_records_output_timing_without_payload(
    monkeypatch,
) -> None:
    payload_marker = "unique-output-payload-should-not-be-retained"
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_attempts=1,
            base_delay=0,
            jitter=0,
        ),
    )
    request = _provider_request("minimax-m2.7")
    upstream_request = _upstream_request("https://example.invalid/v1/messages")
    response = httpx.Response(
        200,
        request=upstream_request,
        headers={"content-type": "text/event-stream"},
        content=(
            b"event: message_start\ndata: {}\n\n"
            b'event: content_block_delta\ndata: {"delta":{"text":"unique-output-payload-should-not-be-retained"}}\n\n'
            b"event: message_stop\ndata: {}\n\n"
        ),
    )
    receipts: list[dict[str, object]] = []

    def record_trace(**fields: object) -> None:
        if fields.get("event") == "provider.fault_attribution":
            receipts.append(fields)

    monkeypatch.setattr(
        "free_claude_code.providers.opencode_go.provider.trace_event",
        record_trace,
    )
    provider._native_http.send = AsyncMock(return_value=response)

    try:
        events = [
            event
            async for event in provider.stream_response(
                request,
                request_id="req_messages_timing",
            )
        ]
    finally:
        await provider.cleanup()

    assert len(events) == 1
    assert len(receipts) == 1
    receipt = receipts[0]
    assert type(receipt["duration_ms"]) is int
    assert type(receipt["time_to_first_token_ms"]) is int
    assert receipt["duration_ms"] >= receipt["time_to_first_token_ms"]
    assert payload_marker not in json.dumps(receipt)


@pytest.mark.asyncio
async def test_messages_stream_retries_pre_payload_transient_status() -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_attempts=2,
            base_delay=0,
            jitter=0,
        ),
    )
    request = _provider_request("minimax-m2.7")
    upstream_request = _upstream_request("https://example.invalid/v1/messages")
    retry_response = httpx.Response(
        503,
        request=upstream_request,
        text="temporarily unavailable",
    )
    success_response = httpx.Response(
        200,
        request=upstream_request,
        headers={"content-type": "text/event-stream"},
        content=(
            b"event: message_start\ndata: {}\n\n"
            b"event: content_block_delta\ndata: {}\n\n"
            b"event: message_stop\ndata: {}\n\n"
        ),
    )
    provider._native_http.send = AsyncMock(
        side_effect=[retry_response, success_response]
    )

    try:
        events = [
            event
            async for event in provider.stream_response(
                request,
                request_id="req_messages_retry",
            )
        ]
    finally:
        await provider.cleanup()

    assert provider._native_http.send.await_count == 2
    assert len(events) == 1
    assert "message_stop" in events[0]


@pytest.mark.asyncio
async def test_messages_stream_accepts_coalesced_small_sse_frames() -> None:
    """HTTP chunk coalescing must not look like one oversized SSE event."""
    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        admission=ProviderAdmissionController(
            provider_name="OPENCODE_GO",
            max_attempts=1,
            base_delay=0,
            jitter=0,
        ),
    )
    request = _provider_request("minimax-m2.7")
    upstream_request = _upstream_request("https://example.invalid/v1/messages")
    frame = b"event: content_block_delta\ndata: {}\n\n"
    success_response = httpx.Response(
        200,
        request=upstream_request,
        headers={"content-type": "text/event-stream"},
        content=frame * 3_000 + b"event: message_stop\ndata: {}\n\n",
    )
    provider._native_http.send = AsyncMock(return_value=success_response)

    try:
        events = [
            event
            async for event in provider.stream_response(
                request,
                request_id="req_messages_coalesced",
            )
        ]
    finally:
        await provider.cleanup()

    assert len(events) == 1
    assert events[0].count("content_block_delta") == 3_000
    assert "message_stop" in events[0]


def test_messages_sse_receipt_extracts_types_without_data() -> None:
    chunk = (
        ": keep-alive\n\n"
        "event: content_block_delta\n"
        'data: {"delta":{"text":"secret"}}\n\n'
        "event: message_stop\n"
        "data: {}\n\n"
    )

    assert _sse_event_types(chunk) == ("content_block_delta", "message_stop")
    assert "secret" not in _sse_event_types(chunk)


def test_messages_sse_ttft_ignores_lifecycle_and_empty_delta_events() -> None:
    lifecycle = (
        "event: message_start\n"
        'data: {"type":"message_start"}\n\n'
        "event: content_block_delta\n"
        "data: {}\n\n"
    )
    output = (
        "event: content_block_delta\n"
        'data: {"delta":{"type":"text_delta","text":"ok"}}\n\n'
    )

    assert _sse_chunk_has_output(lifecycle) is False
    assert _sse_chunk_has_output(output) is True
