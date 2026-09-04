"""OpenAI Codex must participate in the shared pre-network egress policy."""

from unittest.mock import patch

import httpx
import pytest

from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.provider_policy import (
    ProviderEgressGuard,
    ProviderPolicy,
    ProviderPolicyError,
)
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.openai_codex.auth import OpenAIAccess, OpenAIAuthManager
from free_claude_code.providers.openai_codex.provider import OpenAICodexProvider


class _FakeAuth(OpenAIAuthManager):
    def __init__(self) -> None:
        self.access_calls = 0

    async def access(self, *, force_refresh: bool = False) -> OpenAIAccess:
        del force_refresh
        self.access_calls += 1
        return OpenAIAccess("access", "account", False)

    async def recover_unauthorized(self, rejected_token: str) -> OpenAIAccess:
        raise AssertionError(f"unexpected auth recovery for {rejected_token}")


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


def _config(guard: ProviderEgressGuard) -> ProviderConfig:
    return ProviderConfig(
        api_key="",
        base_url="https://chatgpt.com/backend-api/codex",
        provider_family="openai",
        egress_guard=guard,
        rate_limit=100,
        rate_window=1,
        max_concurrency=2,
    )


def _request() -> MessagesRequest:
    return MessagesRequest(
        model="gpt-test",
        max_tokens=16,
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )


@pytest.mark.asyncio
async def test_codex_model_discovery_is_blocked_before_auth_or_transport() -> None:
    transport_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(500, request=request)

    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))
    auth = _FakeAuth()
    client = httpx.AsyncClient(
        base_url="https://chatgpt.com/backend-api/codex/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICodexProvider(
        _config(guard), auth=auth, admission=_admission(), client=client
    )
    try:
        with pytest.raises(ProviderPolicyError, match="before network I/O"):
            await provider.list_model_infos()
    finally:
        await client.aclose()

    assert auth.access_calls == 0
    assert transport_calls == 0
    assert guard.receipt()["blocked_counts"] == {"openai": 1}


@pytest.mark.asyncio
async def test_codex_stream_is_blocked_before_auth_admission_or_transport() -> None:
    transport_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(500, request=request)

    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))
    auth = _FakeAuth()
    admission = _admission()
    client = httpx.AsyncClient(
        base_url="https://chatgpt.com/backend-api/codex/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICodexProvider(
        _config(guard), auth=auth, admission=admission, client=client
    )
    with patch.object(
        admission,
        "new_retry_session",
        wraps=admission.new_retry_session,
    ) as new_retry_session:
        stream = provider.stream_response(_request())
        try:
            with pytest.raises(ProviderPolicyError, match="before network I/O"):
                await anext(stream)
        finally:
            await stream.aclose()
            await client.aclose()
        new_retry_session.assert_not_called()

    assert auth.access_calls == 0
    assert transport_calls == 0
    assert guard.receipt()["blocked_counts"] == {"openai": 1}


@pytest.mark.asyncio
async def test_explicit_openai_primary_can_discover_models_through_same_guard() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"models": [{"slug": "gpt-test", "visibility": "list"}]},
            request=request,
        )

    guard = ProviderEgressGuard(ProviderPolicy("openai", "gpt-test"))
    auth = _FakeAuth()
    client = httpx.AsyncClient(
        base_url="https://chatgpt.com/backend-api/codex/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICodexProvider(
        _config(guard), auth=auth, admission=_admission(), client=client
    )
    try:
        infos = await provider.list_model_infos()
    finally:
        await client.aclose()

    assert {info.model_id for info in infos} == {"gpt-test"}
    assert auth.access_calls == 1
    assert guard.receipt()["counts"] == {"openai": 1}
