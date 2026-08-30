import json
from unittest.mock import AsyncMock, patch

import pytest

from free_claude_code.api.web_tools.local_search import run_local_a3s_search


class _FakeProcess:
    def __init__(self, stdout: bytes, *, returncode: int = 0) -> None:
        self._stdout = stdout
        self.returncode = returncode
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


@pytest.mark.asyncio
async def test_a3s_missing_returns_none_without_spawning() -> None:
    with (
        patch(
            "free_claude_code.api.web_tools.local_search.shutil.which",
            return_value=None,
        ),
        patch(
            "free_claude_code.api.web_tools.local_search.asyncio.create_subprocess_exec",
            new=AsyncMock(),
        ) as spawn,
    ):
        results = await run_local_a3s_search("capital of France")

    assert results is None
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_a3s_uses_http_only_zero_key_engines_and_normalizes_results() -> None:
    payload = {
        "results": [
            {
                "title": "Paris - Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Paris",
                "content": "Paris is the capital and largest city of France.",
            },
            {
                "title": "Ignored non-web URL",
                "url": "file:///tmp/not-web",
                "content": "must not escape",
            },
        ]
    }
    process = _FakeProcess(json.dumps(payload).encode("utf-8"))

    with (
        patch(
            "free_claude_code.api.web_tools.local_search.shutil.which",
            return_value="/usr/local/bin/a3s-search",
        ),
        patch(
            "free_claude_code.api.web_tools.local_search.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ) as spawn,
    ):
        results = await run_local_a3s_search("capital of France")

    assert results == [
        {
            "title": "Paris - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Paris",
            "description": "Paris is the capital and largest city of France.",
        }
    ]
    spawn.assert_awaited_once_with(
        "/usr/local/bin/a3s-search",
        "capital of France",
        "--engines",
        "ddg,wiki,bing",
        "--format",
        "json",
        "--limit",
        "10",
        "--timeout",
        "8",
        stdout=-1,
        stderr=-1,
    )


@pytest.mark.asyncio
async def test_a3s_nonzero_exit_fails_closed_for_outer_fallback() -> None:
    process = _FakeProcess(b"", returncode=7)

    with (
        patch(
            "free_claude_code.api.web_tools.local_search.shutil.which",
            return_value="/usr/local/bin/a3s-search",
        ),
        patch(
            "free_claude_code.api.web_tools.local_search.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ),
    ):
        with pytest.raises(RuntimeError, match="exited with code 7"):
            await run_local_a3s_search("capital of France")
