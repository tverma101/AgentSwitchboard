import httpx
import pytest

from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.opencode_go import OpenCodeGoProvider
from free_claude_code.providers.opencode_go import provider as provider_module


@pytest.mark.asyncio
async def test_go_constructs_both_transport_pools_with_hardened_policy(
    monkeypatch,
) -> None:
    real_async_client = httpx.AsyncClient
    constructor_calls: list[dict[str, object]] = []

    class RecordingAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs) -> None:
            constructor_calls.append(dict(kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", RecordingAsyncClient)

    provider = OpenCodeGoProvider(
        ProviderConfig(
            api_key="test-key",
            base_url="https://example.invalid",
            max_concurrency=2,
        ),
        admission=ProviderAdmissionController(provider_name="OPENCODE_GO"),
    )
    try:
        assert len(constructor_calls) == 2
        for call in constructor_calls:
            assert call["trust_env"] is False
            assert call["follow_redirects"] is False
            limits = call["limits"]
            assert isinstance(limits, httpx.Limits)
            assert limits.max_connections == 4
            assert limits.max_keepalive_connections == 2
            assert limits.keepalive_expiry == 30.0
    finally:
        await provider.cleanup()


@pytest.mark.asyncio
async def test_go_cleanup_is_idempotent(monkeypatch) -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(api_key="test-key", base_url="https://example.invalid"),
        admission=ProviderAdmissionController(provider_name="OPENCODE_GO"),
    )
    chat_cleanup_calls = 0
    responses_close_calls = 0

    async def chat_cleanup() -> None:
        nonlocal chat_cleanup_calls
        chat_cleanup_calls += 1

    async def responses_close() -> None:
        nonlocal responses_close_calls
        responses_close_calls += 1

    monkeypatch.setattr(provider._chat, "cleanup", chat_cleanup)
    monkeypatch.setattr(provider._responses, "close", responses_close)

    await provider.cleanup()
    await provider.cleanup()

    assert chat_cleanup_calls == 1
    assert responses_close_calls == 1
