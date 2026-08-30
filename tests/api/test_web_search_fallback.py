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
            "free_claude_code.api.web_tools.outbound.run_local_a3s_search",
            new=AsyncMock(return_value=None),
        ),
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
            "free_claude_code.api.web_tools.outbound.run_local_a3s_search",
            new=AsyncMock(return_value=None),
        ),
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


@pytest.mark.asyncio
async def test_local_a3s_success_precedes_hosted_backends() -> None:
    local_results = [
        {
            "title": "Local result",
            "url": "https://example.com/local",
            "description": "Merged locally from zero-key engines.",
        }
    ]

    with (
        patch(
            "free_claude_code.api.web_tools.outbound.run_local_a3s_search",
            new=AsyncMock(return_value=local_results),
        ) as local,
        patch(
            "free_claude_code.api.web_tools.outbound._run_firecrawl_search",
            new=AsyncMock(),
        ) as firecrawl,
        patch(
            "free_claude_code.api.web_tools.outbound._run_duckduckgo_search",
            new=AsyncMock(),
        ) as duckduckgo,
    ):
        results = await _run_web_search("capital of France")

    assert results == local_results
    local.assert_awaited_once_with("capital of France")
    firecrawl.assert_not_awaited()
    duckduckgo.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_a3s_failure_falls_back_to_firecrawl() -> None:
    firecrawl_results = [
        {
            "title": "Hosted result",
            "url": "https://example.com/hosted",
        }
    ]

    with (
        patch(
            "free_claude_code.api.web_tools.outbound.run_local_a3s_search",
            new=AsyncMock(side_effect=RuntimeError("local backend failed")),
        ) as local,
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
    local.assert_awaited_once_with("capital of France")
    firecrawl.assert_awaited_once_with("capital of France")
    duckduckgo.assert_not_awaited()
