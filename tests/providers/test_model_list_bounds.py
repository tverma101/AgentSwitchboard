"""Provider model discovery must stay within explicit wire and record budgets."""

from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from free_claude_code.config.provider_catalog import VERTEX_AI_API_ROOT
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.github_models.client import (
    _extract_supported_github_model_ids,
)
from free_claude_code.providers.http import request_model_list_json
from free_claude_code.providers.model_listing import (
    MAX_MODEL_LIST_PAGES,
    MAX_MODEL_LIST_RECORDS,
    MAX_MODEL_LIST_RESPONSE_BYTES,
    ModelListResponseError,
    model_list_items,
)
from free_claude_code.providers.openai_codex.provider import _model_infos
from free_claude_code.providers.vertex import VertexProvider
from free_claude_code.providers.vertex.auth import GoogleAccessTokenProvider
from free_claude_code.providers.vertex.models import extract_vertex_model_page
from tests.providers.support import immediate_admission


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.iterated = False
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.iterated = True
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_model_list_content_length_rejects_before_body_read() -> None:
    stream = _Chunks([b"should-not-be-read"])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": str(MAX_MODEL_LIST_RESPONSE_BYTES + 1)},
            stream=stream,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelListResponseError, match="maximum bytes"):
            await request_model_list_json(
                client,
                "GET",
                "https://provider.test/models",
                provider_name="TEST",
            )
    finally:
        await client.aclose()

    assert stream.iterated is False
    assert stream.closed is True


@pytest.mark.asyncio
async def test_model_list_chunked_response_is_capped_while_streaming() -> None:
    stream = _Chunks([b"x" * MAX_MODEL_LIST_RESPONSE_BYTES, b"y"])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelListResponseError, match="maximum bytes"):
            await request_model_list_json(
                client,
                "GET",
                "https://provider.test/models",
                provider_name="TEST",
            )
    finally:
        await client.aclose()

    assert stream.iterated is True
    assert stream.closed is True


def test_shared_openai_model_list_record_count_is_bounded() -> None:
    with pytest.raises(ModelListResponseError, match="maximum records"):
        model_list_items(
            {"data": [object()] * (MAX_MODEL_LIST_RECORDS + 1)},
            provider_name="TEST",
        )


def test_custom_model_catalog_parsers_share_record_ceiling() -> None:
    with pytest.raises(ModelListResponseError, match="maximum records"):
        _extract_supported_github_model_ids([{}] * (MAX_MODEL_LIST_RECORDS + 1))
    with pytest.raises(ModelListResponseError, match="maximum records"):
        extract_vertex_model_page(
            {"publisherModels": [{}] * (MAX_MODEL_LIST_RECORDS + 1)}
        )
    with pytest.raises(ModelListResponseError, match="maximum records"):
        _model_infos({"models": [{}] * (MAX_MODEL_LIST_RECORDS + 1)})


@pytest.mark.asyncio
async def test_vertex_model_discovery_has_hard_page_ceiling() -> None:
    token_provider = cast(
        GoogleAccessTokenProvider, AsyncMock(return_value="access-token")
    )
    provider = VertexProvider(
        ProviderConfig(api_key="", base_url=VERTEX_AI_API_ROOT),
        project_id="project-123",
        location="global",
        admission=immediate_admission(),
        access_token_provider=token_provider,
    )
    calls = 0

    async def page(_page_token: str | None) -> object:
        nonlocal calls
        calls += 1
        return {
            "publisherModels": [{"name": f"publishers/google/models/model-{calls}"}],
            "nextPageToken": f"page-{calls}",
        }

    try:
        with (
            patch.object(provider, "_list_model_page", side_effect=page) as load_page,
            pytest.raises(ModelListResponseError, match="maximum pages"),
        ):
            await provider.list_model_infos()
        assert load_page.await_count == MAX_MODEL_LIST_PAGES
    finally:
        await provider.cleanup()
