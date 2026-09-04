import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from free_claude_code.core.anthropic import ReasoningReplayMode
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.http import maybe_await_aclose
from free_claude_code.providers.openai_chat import (
    OpenAIChatProfile,
    OpenAIChatProvider,
    OpenAIChatRequestPolicy,
)
from free_claude_code.providers.openai_chat.reasoning import NO_REASONING
from free_claude_code.providers.stream_recovery import RecoveryController
from tests.providers.support import immediate_admission


class _Attempt:
    accepted = False
    failure_retryable = None

    async def succeeded(self) -> None:
        self.accepted = True

    async def aclose(self) -> None:
        return None


class _Provider(OpenAIChatProvider):
    def __init__(self) -> None:
        super().__init__(
            ProviderConfig(
                api_key="test",
                base_url="https://example.invalid/v1",
                rate_limit=100,
                rate_window=1,
            ),
            profile=OpenAIChatProfile(
                OpenAIChatRequestPolicy(
                    provider_name="DEADLINE_TEST",
                    reasoning_replay=ReasoningReplayMode.DISABLED,
                ),
                NO_REASONING,
            ),
            admission=immediate_admission(),
        )

    def _build_request_body(
        self,
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> dict[str, Any]:
        del reasoning
        return {"model": request.model, "messages": []}


async def _delayed_stream():
    await asyncio.sleep(0.04)
    yield SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content="ok", reasoning_content=None, tool_calls=None
                ),
                finish_reason=None,
            )
        ],
        usage=None,
    )
    yield SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=None, reasoning_content=None, tool_calls=None
                ),
                finish_reason="stop",
            )
        ],
        usage=None,
    )


@pytest.mark.asyncio
async def test_openai_chat_releases_message_start_at_wall_clock_deadline() -> None:
    provider = _Provider()
    request = MessagesRequest.model_validate(
        {
            "model": "test-model",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "hello"}],
        }
    )
    attempt = _Attempt()
    create = AsyncMock(return_value=(_delayed_stream(), {"model": "test-model"}, attempt))
    try:
        with (
            patch.object(provider, "_create_stream", new=create),
            patch(
                "free_claude_code.providers.openai_chat.provider.RecoveryController",
                side_effect=lambda: RecoveryController(holdback_seconds=0.01),
            ),
        ):
            stream = provider.stream_response(request)
            first = await asyncio.wait_for(anext(stream), timeout=0.1)
            assert "message_start" in first
            await maybe_await_aclose(stream)
    finally:
        await provider.cleanup()
