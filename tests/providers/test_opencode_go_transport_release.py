from unittest.mock import AsyncMock

import pytest

from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.opencode_go import OpenCodeGoProvider


@pytest.mark.asyncio
async def test_go_protocols_use_hardened_long_lived_transport_pools() -> None:
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
        assert provider._chat._client._client is provider._chat_http
        assert provider._chat_http._trust_env is False
        assert provider._chat_http.follow_redirects is False
        for client in (provider._native_http, provider._chat_http):
            pool = getattr(client._transport, "_pool", None)
            assert pool is not None
            assert pool._max_connections == 4
            assert pool._max_keepalive_connections == 2
            assert pool._keepalive_expiry == 30.0
    finally:
        await provider.cleanup()


@pytest.mark.asyncio
async def test_go_cleanup_is_idempotent(monkeypatch) -> None:
    provider = OpenCodeGoProvider(
        ProviderConfig(api_key="test-key", base_url="https://example.invalid"),
        admission=ProviderAdmissionController(provider_name="OPENCODE_GO"),
    )
    chat_cleanup = AsyncMock()
    responses_close = AsyncMock()
    monkeypatch.setattr(provider._chat, "cleanup", chat_cleanup)
    monkeypatch.setattr(provider._responses, "close", responses_close)

    await provider.cleanup()
    await provider.cleanup()

    chat_cleanup.assert_awaited_once_with()
    responses_close.assert_awaited_once_with()
