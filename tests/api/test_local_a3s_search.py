"""Tests for the optional local A3S web-search backend."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from free_claude_code.api.web_tools.local_search import (
    _A3S_STDOUT_CAP_BYTES,
    run_local_a3s_search,
)


class _FakeStream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self, _limit: int) -> bytes:
        return self._data


class _FakeProcess:
    def __init__(self, stdout: bytes, *, returncode: int | None = None) -> None:
        self.stdout = _FakeStream(stdout)
        self.stderr = _FakeStream(b"")
        self.returncode = returncode
        self._final_returncode = returncode if returncode is not None else 0
        self.killed = False

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = self._final_returncode
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


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
async def test_a3s_uses_explicit_engines_and_normalizes_results() -> None:
    payload = {
        "results": [
            {
                "title": "Paris - Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Paris",
                "content": "Paris is the capital and largest city of France.",
            },
            {"title": "Ignored", "url": "file:///tmp/not-web"},
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
async def test_a3s_oversized_output_fails_and_kills_process() -> None:
    process = _FakeProcess(b"x" * (_A3S_STDOUT_CAP_BYTES + 1))

    with (
        patch(
            "free_claude_code.api.web_tools.local_search.shutil.which",
            return_value="/usr/local/bin/a3s-search",
        ),
        patch(
            "free_claude_code.api.web_tools.local_search.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ),
        pytest.raises(RuntimeError, match="safety cap"),
    ):
        await run_local_a3s_search("capital of France")

    assert process.killed is True


@pytest.mark.asyncio
async def test_a3s_nonzero_exit_and_malformed_output_fail_closed() -> None:
    for stdout, returncode, message in (
        (b"", 7, "exited with code 7"),
        (b"not json", 0, "malformed JSON"),
    ):
        process = _FakeProcess(stdout, returncode=returncode)
        with (
            patch(
                "free_claude_code.api.web_tools.local_search.shutil.which",
                return_value="/usr/local/bin/a3s-search",
            ),
            patch(
                "free_claude_code.api.web_tools.local_search.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            pytest.raises(RuntimeError, match=message),
        ):
            await run_local_a3s_search("capital of France")


@pytest.mark.asyncio
async def test_a3s_timeout_kills_process() -> None:
    process = _FakeProcess(b"")

    async def wait_forever(_process) -> tuple[bytes, bytes]:
        await asyncio.sleep(10)
        return b"", b""

    with (
        patch(
            "free_claude_code.api.web_tools.local_search.shutil.which",
            return_value="/usr/local/bin/a3s-search",
        ),
        patch(
            "free_claude_code.api.web_tools.local_search.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ),
        patch(
            "free_claude_code.api.web_tools.local_search._read_process_output",
            new=wait_forever,
        ),
        patch(
            "free_claude_code.api.web_tools.local_search._A3S_PROCESS_TIMEOUT_SECONDS",
            0.001,
        ),
        pytest.raises(RuntimeError, match="timed out"),
    ):
        await run_local_a3s_search("capital of France")

    assert process.killed is True
