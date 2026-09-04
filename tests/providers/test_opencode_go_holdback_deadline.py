import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.http import maybe_await_aclose
from free_claude_code.providers.opencode_go import OpenCodeGoProvider
from free_claude_code.providers.stream_recovery import RecoveryController


class _ResponsesEvent:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str, exclude_none: bool) -> dict[str, object]:
        del mode, exclude_none
        return self._payload


class _DelayedResponsesStream:
    def __init__(self, events: list[dict[str, object]], delay: float) -> None:
        self._events = iter(_ResponsesEvent(event) for event in events)
        self._delay = delay
        self._first = True
        self.closed = False

    def __aiter__(self) -> AsyncIterator[_ResponsesEvent]:
        return self

    async def __anext__(self) -> _ResponsesEvent:
        if self._first:
            self._first = False
            await asyncio.sleep(self._delay)
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True


def _request() -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": "gpt-5.6-luna",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hello"}],
        }
    )


@pytest.mark.asyncio
async def test_go_responses_releases_message_start_at_wall_clock_deadline() -> None:
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
    delayed = _DelayedResponsesStream(
        [
            {"type": "response.output_text.delta", "delta": "ok"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_deadline",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
        ],
        delay=0.04,
    )
    provider._responses.responses.create = AsyncMock(return_value=delayed)
    try:
        with patch(
            "free_claude_code.providers.opencode_go.provider.RecoveryController",
            side_effect=lambda: RecoveryController(holdback_seconds=0.01),
        ):
            stream = provider.stream_response(
                _request(),
                request_id="req_deadline",
            )
            first = await asyncio.wait_for(anext(stream), timeout=0.1)
            assert "message_start" in first
            await maybe_await_aclose(stream)
        assert delayed.closed
    finally:
        await provider.cleanup()
