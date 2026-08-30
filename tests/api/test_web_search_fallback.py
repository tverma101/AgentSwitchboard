from unittest.mock import AsyncMock, patch

import httpx
import pytest

from free_claude_code.api.web_tools.outbound import _run_web_search


@pytest.mark.asyncio
async def test_firecrawl_failure_falls_back_to_duckduckgo() -> None:
    firecrawl_error = httpx.ConnectError("firecrawl unavailable")
    fallback_results = [
        {
            "title": "Fallback result",
            "url": "https://example.com/fallback",
        }
    ]

    with (
        patch(
            "free_claude_code.api.web_tools.outbound._run_firecrawl_search",
            new=AsyncMock(side_effect=firecrawl_error),
        ) as firecrawl,
        patch(
            "free_claude_code.api.web_tools.outbound._run_duckduckgo_search",
            new=AsyncMock(return_value=fallback_results),
        ) as duckduckgo,
    ):
        results = await _run_web_search("capital of France")

    assert results == fallback_results
    firecrawl.assert_awaited_once_with("capital of France")
    duckduckgo.assert_awaited_once_with("capital of France")


@pytest.mark.asyncio
async def test_firecrawl_success_does_not_call_fallback() -> None:
    firecrawl_results = [
        {
            "title": "Primary result",
            "url": "https://example.com/primary",
        }
    ]

    with (
        patch(
            "free_claude_code.api.web_tools.outbound._run_firecrawl_search",
            new=AsyncMock(return_value=firecrawl_results),
        ) as firecrawl,
        patch(
            "free_claude_code.api.web_tools.outbound._run_duckduckgo_search",
            new=AsyncMock(),
        ) as duckduckgo,
    ):
        results = await _run_web_search("capital of France")

    assert results == firecrawl_results
    firecrawl.assert_awaited_once_with("capital of France")
    duckduckgo.assert_not_awaited()
