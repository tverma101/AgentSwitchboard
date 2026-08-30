import json
from collections.abc import AsyncIterator
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.responses import StreamingResponse

from free_claude_code.api.handlers import MessagesHandler
from free_claude_code.api.web_tools.constants import _MAX_SEARCH_RESULTS
from free_claude_code.api.web_tools.outbound import _run_web_search
from free_claude_code.api.web_tools.request import (
    HIDDEN_WEB_SEARCH_NAME,
    plan_automatic_web_search,
)
from free_claude_code.application.routing import (
    ModelRouter,
    ResolvedModel,
    RoutedMessagesRequest,
)
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.models import Message, MessagesRequest, Tool
from free_claude_code.core.anthropic.stream_contracts import (
    assert_anthropic_stream_contract,
    parse_sse_text,
)
from free_claude_code.core.anthropic.streaming import format_sse_event
from free_claude_code.core.reasoning import ReasoningPolicy


class FixedProviderModelRouter(ModelRouter):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def resolve_messages_request(
        self,
        request: MessagesRequest,
        *,
        parent_route: ResolvedModel | None = None,
    ) -> RoutedMessagesRequest:
        resolved = ResolvedModel(
            original_model=request.model,
            provider_id="openai_chat",
            provider_model="upstream-model",
            provider_model_ref="openai_chat/upstream-model",
            reasoning_preference=ReasoningPreference.OFF,
        )
        routed = request.model_copy(deep=True)
        routed.model = resolved.provider_model
        return RoutedMessagesRequest(
            request=routed,
            resolved=resolved,
            reasoning=ReasoningPolicy.off(),
        )


class ScriptedSelectionProvider:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.requests: list[MessagesRequest] = []
        self.close_count = 0

    def preflight_stream(
        self, request: MessagesRequest, *, reasoning: ReasoningPolicy
    ) -> None:
        return None

    async def stream_response(
        self,
        request: MessagesRequest,
        *,
        input_tokens: int,
        request_id: str,
        response_model: str,
        reasoning: ReasoningPolicy,
    ) -> AsyncIterator[str]:
        self.requests.append(request)
        try:
            for event in self.events:
                yield event
        finally:
            self.close_count += 1


def _automatic_request() -> MessagesRequest:
    return MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        stream=True,
        messages=[Message(role="user", content="Find the latest docs")],
        tools=[Tool(name="web_search", type="web_search_20250305")],
        tool_choice={"type": "auto"},
    )


def _provider_text_events(text: str) -> list[str]:
    return [
        format_sse_event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_provider",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "gateway-model",
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 11, "output_tokens": 1},
                },
            },
        ),
        format_sse_event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        format_sse_event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        format_sse_event(
            "content_block_stop", {"type": "content_block_stop", "index": 0}
        ),
        format_sse_event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 3},
            },
        ),
        format_sse_event("message_stop", {"type": "message_stop"}),
    ]


def _provider_tool_events(query: str) -> list[str]:
    return [
        format_sse_event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_provider",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "gateway-model",
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 17, "output_tokens": 1},
                },
            },
        ),
        format_sse_event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "call_0",
                    "name": HIDDEN_WEB_SEARCH_NAME,
                    "input": {},
                },
            },
        ),
        format_sse_event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": json.dumps({"query": query}),
                },
            },
        ),
        format_sse_event(
            "content_block_stop", {"type": "content_block_stop", "index": 0}
        ),
        format_sse_event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 9},
            },
        ),
        format_sse_event("message_stop", {"type": "message_stop"}),
    ]


async def _body_text(response: StreamingResponse) -> str:
    return "".join(
        [
            chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
            async for chunk in response.body_iterator
        ]
    )


def _service(provider: ScriptedSelectionProvider) -> MessagesHandler:
    settings = Settings.model_validate({"ENABLE_WEB_SERVER_TOOLS": True})
    return MessagesHandler(
        settings,
        provider_resolver=lambda _: provider,
        model_router=FixedProviderModelRouter(settings),
    )


def test_plans_exact_claude_automatic_web_search() -> None:
    request = _automatic_request()

    plan = plan_automatic_web_search(request, web_tools_enabled=True)

    assert plan is not None
    assert plan.request.tools is not None
    assert [tool.name for tool in plan.request.tools] == [HIDDEN_WEB_SEARCH_NAME]
    assert request.tools is not None
    assert request.tools[0].name == "web_search"


@pytest.mark.asyncio
async def test_provider_decline_replays_original_provider_stream() -> None:
    events = _provider_text_events("No search needed")
    provider = ScriptedSelectionProvider(events)

    with patch(
        "free_claude_code.api.web_tools.outbound._run_web_search",
        new_callable=AsyncMock,
    ) as search:
        response = await _service(provider).create(
            _automatic_request(), request_id="req_auto_decline"
        )
        assert isinstance(response, StreamingResponse)
        raw = await _body_text(response)

    assert raw == "".join(events)
    search.assert_not_awaited()
    assert provider.close_count == 1
    assert len(provider.requests) == 1
    assert provider.requests[0].tools is not None
    assert [tool.name for tool in provider.requests[0].tools] == [
        HIDDEN_WEB_SEARCH_NAME
    ]


@pytest.mark.asyncio
async def test_provider_selected_query_executes_local_search_once() -> None:
    provider = ScriptedSelectionProvider(_provider_tool_events("model selected query"))

    async def fake_search(query: str) -> list[dict[str, str]]:
        assert query == "model selected query"
        return [{"title": "Result", "url": "https://example.com/result"}]

    with patch(
        "free_claude_code.api.web_tools.outbound._run_web_search",
        side_effect=fake_search,
    ) as search:
        response = await _service(provider).create(
            _automatic_request(), request_id="req_auto_selected"
        )
        assert isinstance(response, StreamingResponse)
        raw = await _body_text(response)

    events = parse_sse_text(raw)
    assert_anthropic_stream_contract(events)
    search.assert_awaited_once_with("model selected query")
    assert HIDDEN_WEB_SEARCH_NAME not in raw
    assert "call_0" not in raw
    assert "https://example.com/result" in raw
    starts = [event for event in events if event.event == "content_block_start"]
    assert [event.data["content_block"]["type"] for event in starts] == [
        "server_tool_use",
        "web_search_tool_result",
        "text",
    ]
    assert provider.close_count == 1
    assert len(provider.requests) == 1


class _ResponseContext:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    async def __aenter__(self) -> httpx.Response:
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FirecrawlClient:
    constructor_kwargs: ClassVar[dict[str, object]] = {}
    stream_args: ClassVar[tuple[object, ...]] = ()
    stream_kwargs: ClassVar[dict[str, object]] = {}

    def __init__(self, **kwargs: object) -> None:
        type(self).constructor_kwargs = kwargs

    async def __aenter__(self) -> _FirecrawlClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def stream(self, *args: object, **kwargs: object) -> _ResponseContext:
        type(self).stream_args = args
        type(self).stream_kwargs = kwargs
        request = httpx.Request("POST", "https://api.firecrawl.dev/v2/search")
        payload = {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "Firecrawl result",
                        "url": "https://example.com/firecrawl",
                        "description": "structured result",
                    }
                ]
            },
        }
        response = httpx.Response(
            200,
            request=request,
            content=json.dumps(payload).encode("utf-8"),
        )
        return _ResponseContext(response)


@pytest.mark.asyncio
async def test_firecrawl_keyless_search_uses_no_authorization_header() -> None:
    with patch(
        "free_claude_code.api.web_tools.outbound.httpx.AsyncClient",
        _FirecrawlClient,
    ):
        results = await _run_web_search("claude docs")

    assert results == [
        {
            "title": "Firecrawl result",
            "url": "https://example.com/firecrawl",
            "description": "structured result",
        }
    ]
    assert _FirecrawlClient.stream_args == (
        "POST",
        "https://api.firecrawl.dev/v2/search",
    )
    headers = _FirecrawlClient.constructor_kwargs["headers"]
    assert isinstance(headers, dict)
    assert "Authorization" not in headers
    assert _FirecrawlClient.stream_kwargs["json"] == {
        "query": "claude docs",
        "limit": _MAX_SEARCH_RESULTS,
    }
