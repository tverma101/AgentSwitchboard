import asyncio
from collections.abc import AsyncIterator

import pytest

from free_claude_code.providers.http import maybe_await_aclose
from free_claude_code.providers.stream_recovery import (
    RecoveryController,
    RecoveryStreamSignal,
)


@pytest.mark.asyncio
async def test_deadline_signal_preserves_same_pending_upstream_read() -> None:
    recovery = RecoveryController(holdback_seconds=0.01)
    assert recovery.push("event: message_start\n\n") == []
    recovery.restart_holdback_deadline()
    gate = asyncio.Event()
    cancelled = False

    async def source() -> AsyncIterator[str]:
        nonlocal cancelled
        try:
            await gate.wait()
            yield "upstream-item"
        except asyncio.CancelledError:
            cancelled = True
            raise

    wrapped = recovery.iterate_with_holdback_deadline(source())
    signal = await asyncio.wait_for(anext(wrapped), timeout=0.1)
    assert signal is RecoveryStreamSignal.HOLDBACK_DEADLINE
    assert cancelled is False
    assert recovery.flush() == ["event: message_start\n\n"]
    gate.set()
    assert await asyncio.wait_for(anext(wrapped), timeout=0.1) == "upstream-item"
    assert cancelled is False
    await maybe_await_aclose(wrapped)


@pytest.mark.asyncio
async def test_closing_after_deadline_cancels_owned_pending_read() -> None:
    recovery = RecoveryController(holdback_seconds=0.01)
    assert recovery.push("start") == []
    recovery.restart_holdback_deadline()
    cancelled = asyncio.Event()

    async def source() -> AsyncIterator[str]:
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        except asyncio.CancelledError:
            cancelled.set()
            raise

    wrapped = recovery.iterate_with_holdback_deadline(source())
    assert (
        await asyncio.wait_for(anext(wrapped), timeout=0.1)
        is RecoveryStreamSignal.HOLDBACK_DEADLINE
    )
    assert recovery.flush() == ["start"]
    await maybe_await_aclose(wrapped)
    await asyncio.wait_for(cancelled.wait(), timeout=0.1)


@pytest.mark.asyncio
async def test_after_commit_iteration_has_no_deadline_signal() -> None:
    recovery = RecoveryController(holdback_seconds=0.01)
    assert recovery.push("start") == []
    assert recovery.flush() == ["start"]

    async def source() -> AsyncIterator[str]:
        yield "a"
        yield "b"

    assert [item async for item in recovery.iterate_with_holdback_deadline(source())] == [
        "a",
        "b",
    ]
