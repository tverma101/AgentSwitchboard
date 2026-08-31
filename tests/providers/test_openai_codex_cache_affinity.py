import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.reasoning import ReasoningPolicy
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.openai_codex.auth import (
    OpenAIAccess,
    OpenAIAuthManager,
)
from free_claude_code.providers.openai_codex.provider import OpenAICodexProvider


class _FakeAuth(OpenAIAuthManager):
    async def access(self, *, force_refresh: bool = False) -> OpenAIAccess:
        return OpenAIAccess("access_1", "account_1", False)

    async def recover_unauthorized(self, rejected_token: str) -> OpenAIAccess:
        raise AssertionError(f"unexpected auth recovery for {rejected_token}")


def _config() -> ProviderConfig:
    return ProviderConfig(
        api_key="",
        base_url="https://chatgpt.com/backend-api/codex",
        rate_limit=100,
        rate_window=1,
        max_concurrency=2,
    )


def _admission() -> ProviderAdmissionController:
    return ProviderAdmissionController(
        provider_name="openai",
        rate_limit=100,
        rate_window=1,
        max_concurrency=2,
        base_delay=0,
        max_delay=0,
        jitter=0,
    )


def _complete_stream(text: str) -> str:
    events: tuple[tuple[str, dict[str, Any]], ...] = (
        (
            "response.output_text.delta",
            {"type": "response.output_text.delta", "delta": text},
        ),
        (
            "response.completed",
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                },
            },
        ),
    )
    return "".join(
        f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
        for event_type, payload in events
    )


async def _collect(stream: AsyncIterator[str]) -> str:
    return "".join([chunk async for chunk in stream])


@pytest.mark.asyncio
async def test_codex_session_header_reuses_prompt_cache_identity() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text=_complete_stream("ok"),
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    client = httpx.AsyncClient(
        base_url="https://chatgpt.com/backend-api/codex/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICodexProvider(
        _config(), auth=_FakeAuth(), admission=_admission(), client=client
    )
    session_id = "stable-session-123"
    request = MessagesRequest(
        model="gpt-test",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
        claude_session_id=session_id,
    )

    await _collect(
        provider.stream_response(
            request,
            input_tokens=3,
            request_id="req_cache_affinity",
            response_model="claude-opus-4",
            reasoning=ReasoningPolicy.provider_default(),
        )
    )

    assert len(requests) == 1
    upstream = requests[0]
    payload = json.loads(upstream.content)
    assert payload["prompt_cache_key"] == session_id
    assert upstream.headers["session-id"] == session_id
    assert upstream.headers["session_id"] == session_id
    await client.aclose()
