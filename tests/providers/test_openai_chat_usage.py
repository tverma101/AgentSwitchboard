"""OpenAI-chat streamed usage helper tests."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import openai
import pytest
from httpx import Request, Response

from free_claude_code.core.anthropic import ReasoningReplayMode
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.anthropic.stream_contracts import parse_sse_text
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.openai_chat import (
    OpenAIChatProfile,
    OpenAIChatProvider,
    OpenAIChatRequestPolicy,
)
from free_claude_code.providers.openai_chat.reasoning import NO_REASONING
from free_claude_code.providers.openai_chat.usage import (
    cache_usage_fields,
    clone_without_stream_usage,
    is_stream_usage_rejection,
    request_stream_usage,
    usage_int,
    usage_nested_int,
)
from tests.providers.request_factory import make_messages_request
from tests.providers.support import immediate_admission


class _UsageTestProvider(OpenAIChatProvider):
    def __init__(self):
        super().__init__(
            ProviderConfig(
                api_key="test_key",
                base_url="https://provider.example/v1",
                rate_limit=100,
                rate_window=60,
            ),
            profile=OpenAIChatProfile(
                OpenAIChatRequestPolicy(
                    provider_name="USAGE_TEST",
                    reasoning_replay=ReasoningReplayMode.DISABLED,
                ),
                NO_REASONING,
                usage_fields=cache_usage_fields,
            ),
            admission=immediate_admission(),
        )

    def _build_request_body(
        self,
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> dict:
        return {"model": request.model, "messages": [{"role": "user", "content": "x"}]}


def _bad_request(message: str, body: object | None = None) -> openai.BadRequestError:
    response = Response(
        400,
        request=Request("POST", "https://provider.example/v1/chat/completions"),
    )
    return openai.BadRequestError(message, response=response, body=body)


async def _stream(chunks):
    for chunk in chunks:
        yield chunk


def _chunk(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    usage: Any = None,
):
    if content is None and finish_reason is None:
        return SimpleNamespace(choices=[], usage=usage)
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    reasoning_content=None,
                    tool_calls=None,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


def test_request_stream_usage_adds_stream_options_when_absent():
    body = {"model": "m"}

    request_stream_usage(body)

    assert body["stream_options"] == {"include_usage": True}


def test_request_stream_usage_preserves_existing_stream_options():
    stream_options = {"foo": "bar"}
    body = {"model": "m", "stream_options": stream_options}

    request_stream_usage(body)

    assert body["stream_options"] == {"foo": "bar", "include_usage": True}
    assert body["stream_options"] is stream_options


def test_clone_without_stream_usage_removes_only_include_usage():
    body = {
        "model": "m",
        "stream_options": {"foo": "bar", "include_usage": True},
    }

    retry_body = clone_without_stream_usage(body)

    assert retry_body == {"model": "m", "stream_options": {"foo": "bar"}}
    assert body["stream_options"] == {"foo": "bar", "include_usage": True}


def test_clone_without_stream_usage_drops_empty_stream_options():
    body = {"model": "m", "stream_options": {"include_usage": True}}

    retry_body = clone_without_stream_usage(body)

    assert retry_body == {"model": "m"}


def test_usage_int_reads_dict_object_and_model_extra():
    assert usage_int({"prompt_tokens": 11}, "prompt_tokens") == 11
    assert usage_int(SimpleNamespace(completion_tokens=7), "completion_tokens") == 7
    assert (
        usage_int(
            SimpleNamespace(model_extra={"prompt_cache_hit_tokens": 3}),
            "prompt_cache_hit_tokens",
        )
        == 3
    )
    assert usage_int(SimpleNamespace(prompt_tokens=None), "prompt_tokens") is None
    assert usage_int({"prompt_tokens": True}, "prompt_tokens") is None


def test_usage_nested_int_reads_sdk_and_mapping_shapes():
    assert (
        usage_nested_int(
            {"prompt_tokens_details": {"cached_tokens": 31}},
            "prompt_tokens_details",
            "cached_tokens",
        )
        == 31
    )
    assert (
        usage_nested_int(
            SimpleNamespace(prompt_tokens_details=SimpleNamespace(cached_tokens=29)),
            "prompt_tokens_details",
            "cached_tokens",
        )
        == 29
    )


def test_cache_usage_fields_maps_hit_and_miss_to_disjoint_anthropic_usage():
    usage = SimpleNamespace(
        prompt_tokens=40,
        prompt_cache_hit_tokens=31,
        prompt_cache_miss_tokens=9,
    )

    assert cache_usage_fields(usage) == {
        "cache_read_input_tokens": 31,
        "input_tokens": 9,
    }


def test_cache_usage_fields_preserves_explicit_cache_write_counter():
    usage = {
        "prompt_tokens": 40,
        "prompt_cache_hit_tokens": 31,
        "prompt_cache_miss_tokens": 9,
        "prompt_cache_write_tokens": 3,
    }

    assert cache_usage_fields(usage) == {
        "cache_read_input_tokens": 31,
        "input_tokens": 9,
        "cache_creation_input_tokens": 3,
    }


def test_cache_usage_fields_supports_openai_nested_cached_tokens():
    usage = SimpleNamespace(
        prompt_tokens=40,
        prompt_tokens_details=SimpleNamespace(cached_tokens=31),
    )

    assert cache_usage_fields(usage) == {
        "cache_read_input_tokens": 31,
        "input_tokens": 9,
    }


def test_cache_usage_fields_omits_cache_read_without_disjoint_input():
    usage = {"prompt_tokens_details": {"cached_tokens": 31}}

    assert cache_usage_fields(usage) == {}


def test_cache_usage_fields_does_not_invent_uncached_count_from_invalid_total():
    usage = {
        "prompt_tokens": 10,
        "prompt_tokens_details": {"cached_tokens": 20},
    }

    assert cache_usage_fields(usage) == {}


def test_cache_usage_fields_ignores_negative_cache_counters():
    usage = {
        "prompt_tokens": 40,
        "prompt_cache_hit_tokens": -1,
        "prompt_cache_miss_tokens": -1,
        "prompt_cache_write_tokens": -1,
    }

    assert cache_usage_fields(usage) == {}


def test_cache_usage_fields_falls_back_when_miss_exceeds_prompt_total():
    usage = {
        "prompt_tokens": 40,
        "prompt_cache_hit_tokens": 31,
        "prompt_cache_miss_tokens": 50,
    }

    assert cache_usage_fields(usage) == {
        "cache_read_input_tokens": 31,
        "input_tokens": 9,
    }


def test_stream_usage_rejection_matches_usage_option_400():
    error = _bad_request(
        "Unrecognized request argument supplied: stream_options",
        {"error": {"message": "stream_options is unsupported"}},
    )

    assert is_stream_usage_rejection(error)


def test_stream_usage_rejection_does_not_match_unrelated_400():
    error = _bad_request(
        "messages: invalid role",
        {"error": {"message": "messages contains invalid role"}},
    )

    assert not is_stream_usage_rejection(error)


@pytest.mark.asyncio
async def test_openai_chat_stream_keeps_final_usage_at_governed_prompt_estimate():
    provider = _UsageTestProvider()
    request = make_messages_request(model="m")
    usage = SimpleNamespace(prompt_tokens=22, completion_tokens=4)
    create = AsyncMock(
        return_value=_stream(
            [
                _chunk(content="hello"),
                _chunk(finish_reason="stop"),
                _chunk(usage=usage),
            ]
        )
    )

    with patch.object(provider._client.chat.completions, "create", create):
        events = [
            event async for event in provider.stream_response(request, input_tokens=7)
        ]

    create.assert_awaited_once()
    await_args = create.await_args
    assert await_args is not None
    assert await_args.kwargs["stream_options"] == {"include_usage": True}
    parsed = parse_sse_text("".join(events))
    start_usage = next(
        event.data["message"]["usage"]
        for event in parsed
        if event.event == "message_start"
    )
    final_usage = next(
        event.data["usage"] for event in parsed if event.event == "message_delta"
    )
    assert start_usage["input_tokens"] == 7
    assert final_usage == {"input_tokens": 7, "output_tokens": 4}


@pytest.mark.asyncio
async def test_openai_chat_stream_reconciles_cache_to_governed_prompt_estimate():
    provider = _UsageTestProvider()
    request = make_messages_request(model="m")
    usage = SimpleNamespace(
        prompt_tokens=40,
        completion_tokens=4,
        prompt_cache_hit_tokens=31,
        prompt_cache_miss_tokens=9,
    )
    create = AsyncMock(
        return_value=_stream(
            [
                _chunk(content="hello"),
                _chunk(finish_reason="stop"),
                _chunk(usage=usage),
            ]
        )
    )

    with patch.object(provider._client.chat.completions, "create", create):
        events = [
            event async for event in provider.stream_response(request, input_tokens=40)
        ]

    final_usage = next(
        event.data["usage"]
        for event in parse_sse_text("".join(events))
        if event.event == "message_delta"
    )
    assert final_usage == {
        "input_tokens": 9,
        "output_tokens": 4,
        "cache_read_input_tokens": 31,
    }
    assert final_usage["input_tokens"] + final_usage["cache_read_input_tokens"] == 40


@pytest.mark.asyncio
async def test_openai_chat_stream_does_not_double_count_cached_prompt_tokens():
    provider = _UsageTestProvider()
    request = make_messages_request(model="m")
    usage = SimpleNamespace(
        prompt_tokens=40,
        completion_tokens=4,
        prompt_cache_hit_tokens=31,
        prompt_cache_miss_tokens=9,
    )
    create = AsyncMock(
        return_value=_stream(
            [
                _chunk(content="hello"),
                _chunk(finish_reason="stop"),
                _chunk(usage=usage),
            ]
        )
    )

    with patch.object(provider._client.chat.completions, "create", create):
        events = [
            event async for event in provider.stream_response(request, input_tokens=40)
        ]

    final_usage = next(
        event.data["usage"]
        for event in parse_sse_text("".join(events))
        if event.event == "message_delta"
    )
    assert final_usage == {
        "input_tokens": 9,
        "output_tokens": 4,
        "cache_read_input_tokens": 31,
    }
    assert final_usage["input_tokens"] + final_usage["cache_read_input_tokens"] == 40
    assert "cache_creation_input_tokens" not in final_usage


@pytest.mark.asyncio
async def test_openai_chat_stream_reports_explicit_cache_write_separately():
    provider = _UsageTestProvider()
    request = make_messages_request(model="m")
    usage = SimpleNamespace(
        prompt_tokens=40,
        completion_tokens=4,
        prompt_cache_hit_tokens=31,
        prompt_cache_miss_tokens=9,
        prompt_cache_write_tokens=3,
    )
    create = AsyncMock(
        return_value=_stream(
            [
                _chunk(content="hello"),
                _chunk(finish_reason="stop"),
                _chunk(usage=usage),
            ]
        )
    )

    with patch.object(provider._client.chat.completions, "create", create):
        events = [
            event async for event in provider.stream_response(request, input_tokens=40)
        ]

    final_usage = next(
        event.data["usage"]
        for event in parse_sse_text("".join(events))
        if event.event == "message_delta"
    )
    assert final_usage == {
        "input_tokens": 6,
        "output_tokens": 4,
        "cache_read_input_tokens": 31,
        "cache_creation_input_tokens": 3,
    }
    assert (
        final_usage["input_tokens"]
        + final_usage["cache_read_input_tokens"]
        + final_usage["cache_creation_input_tokens"]
        == 40
    )


@pytest.mark.asyncio
async def test_openai_chat_stream_omits_impossible_cached_breakdown():
    provider = _UsageTestProvider()
    request = make_messages_request(model="m")
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=1,
        prompt_tokens_details=SimpleNamespace(cached_tokens=20),
    )
    create = AsyncMock(
        return_value=_stream(
            [
                _chunk(content="hello"),
                _chunk(finish_reason="stop"),
                _chunk(usage=usage),
            ]
        )
    )

    with patch.object(provider._client.chat.completions, "create", create):
        events = [event async for event in provider.stream_response(request)]

    final_usage = next(
        event.data["usage"]
        for event in parse_sse_text("".join(events))
        if event.event == "message_delta"
    )
    assert final_usage == {"input_tokens": 10, "output_tokens": 1}


@pytest.mark.asyncio
async def test_openai_chat_stream_ignores_negative_cache_counters():
    provider = _UsageTestProvider()
    request = make_messages_request(model="m")
    usage = SimpleNamespace(
        prompt_tokens=40,
        completion_tokens=4,
        prompt_cache_hit_tokens=-1,
        prompt_cache_miss_tokens=-1,
        prompt_cache_write_tokens=-1,
    )
    create = AsyncMock(
        return_value=_stream(
            [
                _chunk(content="hello"),
                _chunk(finish_reason="stop"),
                _chunk(usage=usage),
            ]
        )
    )

    with patch.object(provider._client.chat.completions, "create", create):
        events = [event async for event in provider.stream_response(request)]

    final_usage = next(
        event.data["usage"]
        for event in parse_sse_text("".join(events))
        if event.event == "message_delta"
    )
    assert final_usage == {"input_tokens": 40, "output_tokens": 4}


@pytest.mark.asyncio
async def test_openai_chat_stream_falls_back_from_negative_prompt_usage():
    provider = _UsageTestProvider()
    request = make_messages_request(model="m")
    usage = SimpleNamespace(
        prompt_tokens=-1,
        completion_tokens=-1,
    )
    create = AsyncMock(
        return_value=_stream(
            [
                _chunk(content="hello"),
                _chunk(finish_reason="stop"),
                _chunk(usage=usage),
            ]
        )
    )

    with patch.object(provider._client.chat.completions, "create", create):
        events = [
            event async for event in provider.stream_response(request, input_tokens=7)
        ]

    final_usage = next(
        event.data["usage"]
        for event in parse_sse_text("".join(events))
        if event.event == "message_delta"
    )
    assert final_usage["input_tokens"] == 7
    assert final_usage["output_tokens"] > 0


@pytest.mark.asyncio
async def test_openai_chat_stream_falls_back_from_impossible_cache_miss():
    provider = _UsageTestProvider()
    request = make_messages_request(model="m")
    usage = SimpleNamespace(
        prompt_tokens=40,
        completion_tokens=4,
        prompt_cache_hit_tokens=31,
        prompt_cache_miss_tokens=50,
    )
    create = AsyncMock(
        return_value=_stream(
            [
                _chunk(content="hello"),
                _chunk(finish_reason="stop"),
                _chunk(usage=usage),
            ]
        )
    )

    with patch.object(provider._client.chat.completions, "create", create):
        events = [event async for event in provider.stream_response(request)]

    final_usage = next(
        event.data["usage"]
        for event in parse_sse_text("".join(events))
        if event.event == "message_delta"
    )
    assert final_usage == {
        "input_tokens": 9,
        "output_tokens": 4,
        "cache_read_input_tokens": 31,
    }


@pytest.mark.asyncio
async def test_openai_chat_stream_keeps_response_model_separate_from_upstream_model():
    provider = _UsageTestProvider()
    request = make_messages_request(model="upstream/model")
    create = AsyncMock(
        return_value=_stream(
            [
                _chunk(content="hello"),
                _chunk(finish_reason="stop"),
            ]
        )
    )

    with patch.object(provider._client.chat.completions, "create", create):
        events = [
            event
            async for event in provider.stream_response(
                request,
                response_model="anthropic/test/upstream/model",
            )
        ]

    assert create.await_args is not None
    assert create.await_args.kwargs["model"] == "upstream/model"
    message_start = next(
        event.data["message"]
        for event in parse_sse_text("".join(events))
        if event.event == "message_start"
    )
    assert message_start["model"] == "anthropic/test/upstream/model"


@pytest.mark.asyncio
async def test_openai_chat_stream_retries_without_usage_when_option_is_rejected():
    provider = _UsageTestProvider()
    body = {"model": "m", "messages": [{"role": "user", "content": "x"}]}
    request_stream_usage(body)
    create = AsyncMock(
        side_effect=[
            _bad_request(
                "stream_options is unsupported",
                {"error": {"message": "stream_options is unsupported"}},
            ),
            object(),
        ]
    )

    with patch.object(provider._client.chat.completions, "create", create):
        _stream_obj, used_body, attempt = await provider._create_stream(
            body,
            provider._admission.new_retry_session(),
        )
        await attempt.aclose()

    assert create.await_count == 2
    assert create.await_args_list[0].kwargs["stream_options"] == {"include_usage": True}
    assert "stream_options" not in create.await_args_list[1].kwargs
    assert "stream_options" not in used_body
