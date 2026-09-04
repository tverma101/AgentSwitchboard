"""Native model-discovery clients must obey the shared pre-network egress guard."""

from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from free_claude_code.config.provider_catalog import (
    CLOUDFLARE_AI_REST_ROOT,
    GITHUB_MODELS_DEFAULT_BASE,
    VERTEX_AI_API_ROOT,
)
from free_claude_code.core.provider_policy import (
    ProviderEgressGuard,
    ProviderPolicy,
    ProviderPolicyError,
)
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.cloudflare import CloudflareProvider
from free_claude_code.providers.github_models import GitHubModelsProvider
from free_claude_code.providers.vertex import VertexProvider
from free_claude_code.providers.vertex.auth import GoogleAccessTokenProvider
from tests.providers.support import immediate_admission


def _blocked_guard() -> ProviderEgressGuard:
    return ProviderEgressGuard(ProviderPolicy("bai", "controller"))


@pytest.mark.asyncio
async def test_cloudflare_native_discovery_is_blocked_before_http() -> None:
    guard = _blocked_guard()
    provider = CloudflareProvider(
        ProviderConfig(
            api_key="token",
            base_url=CLOUDFLARE_AI_REST_ROOT,
            provider_family="cloudflare",
            egress_guard=guard,
        ),
        account_id="account-123",
        admission=immediate_admission(),
    )
    with patch.object(
        provider._model_list_client, "get", new_callable=AsyncMock
    ) as get:
        try:
            with pytest.raises(ProviderPolicyError, match="before network I/O"):
                await provider.list_model_infos()
        finally:
            await provider.cleanup()
    get.assert_not_awaited()
    assert guard.receipt()["blocked_counts"] == {"cloudflare": 1}


@pytest.mark.asyncio
async def test_github_models_native_discovery_is_blocked_before_http() -> None:
    guard = _blocked_guard()
    provider = GitHubModelsProvider(
        ProviderConfig(
            api_key="token",
            base_url=GITHUB_MODELS_DEFAULT_BASE,
            provider_family="github_models",
            egress_guard=guard,
        ),
        admission=immediate_admission(),
    )
    with patch.object(
        provider._model_list_client, "get", new_callable=AsyncMock
    ) as get:
        try:
            with pytest.raises(ProviderPolicyError, match="before network I/O"):
                await provider.list_model_infos()
        finally:
            await provider.cleanup()
    get.assert_not_awaited()
    assert guard.receipt()["blocked_counts"] == {"github_models": 1}


@pytest.mark.asyncio
async def test_vertex_native_discovery_is_blocked_before_token_or_http() -> None:
    guard = _blocked_guard()
    token_mock = AsyncMock(return_value="access-token")
    token_provider = cast(GoogleAccessTokenProvider, token_mock)
    provider = VertexProvider(
        ProviderConfig(
            api_key="",
            base_url=VERTEX_AI_API_ROOT,
            provider_family="vertex",
            egress_guard=guard,
        ),
        project_id="project-123",
        location="global",
        admission=immediate_admission(),
        access_token_provider=token_provider,
    )
    with patch.object(
        provider._model_list_client, "get", new_callable=AsyncMock
    ) as get:
        try:
            with pytest.raises(ProviderPolicyError, match="before network I/O"):
                await provider.list_model_infos()
        finally:
            await provider.cleanup()
    token_mock.assert_not_awaited()
    get.assert_not_awaited()
    assert guard.receipt()["blocked_counts"] == {"vertex": 1}
