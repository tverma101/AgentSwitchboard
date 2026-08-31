import asyncio
from collections.abc import AsyncIterator
from unittest.mock import patch

import httpx
import pytest

from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.failures import ExecutionFailure
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.openai_codex.auth import (
    OpenAIAccess,
    OpenAIAuthManager,
)
from free_claude_code.providers.openai_codex.provider import OpenAICodexProvider
from free_claude_code.providers.stream_recovery import RecoveryController


class _FakeAuth(OpenAIAuthManager):
    async def access(self, *, force_refresh: bool = False) -> OpenAIAccess:
        del force_refresh
        return OpenAIAccess("access", "account", False)

    async def recover_unauthorized(self, rejected_token: str) -> OpenAIAccess:
        raise AssertionError(f"unexpected auth recovery for {rejected_token}")


class _DelayedReadFailure(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        await asyncio.sleep(0.04)
        raise httpx.ReadError("upstream stream stalled then disconnected")
        yield b""  # pragma: no cover - keeps this an async generator


def _config() -> ProviderConfig:
    return ProviderConfig(
        api_key="",
        base_url="https://chatgpt.com/backend-api/codex",
        rate_limit=100,
        rate_window=1,
        max_concurrency=2,
    )


def _request() -> MessagesRequest:
    return MessagesRequest(
        model="gpt-test",
        max_tokens=1024,
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )


async def _drain(stream: AsyncIterator[str]) -> None:
    async for _chunk in stream:
        pass


@pytest.mark.asyncio
async def test_accepted_quiet_codex_stream_commits_deadline_without_poisoning_retry_gate() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_DelayedReadFailure(),
            request=request,
        )

    client = httpx.AsyncClient(
        base_url="https://chatgpt.com/backend-api/codex/",
        transport=httpx.MockTransport(handler),
    )
    admission = ProviderAdmissionController(
        provider_name="openai",
        rate_limit=100,
        rate_window=1,
        max_concurrency=2,
        max_attempts=2,
        base_delay=0,
        max_delay=0,
        jitter=0,
    )
    provider = OpenAICodexProvider(
        _config(),
        auth=_FakeAuth(),
        admission=admission,
        client=client,
    )

    with patch(
        "free_claude_code.providers.openai_codex.provider.RecoveryController",
        side_effect=lambda: RecoveryController(holdback_seconds=0.01),
    ):
        stream = provider.stream_response(_request())
        first = await asyncio.wait_for(anext(stream), timeout=0.1)
        assert "message_start" in first

        with pytest.raises(ExecutionFailure):
            await asyncio.wait_for(_drain(stream), timeout=0.2)

    # A committed request cannot retry invisibly. Its failed attempt must also
    # release admission ownership so the next independent request is not stuck
    # behind a recovery episode that the old request can never probe.
    probe = await asyncio.wait_for(
        admission.open_attempt(admission.new_retry_session()), timeout=0.1
    )
    await probe.aclose()
    await client.aclose()
