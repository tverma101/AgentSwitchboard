import asyncio

import pytest

from free_claude_code.providers.stream_recovery import RecoveryController


@pytest.mark.asyncio
async def test_holdback_deadline_expires_without_cancelling_upstream_read() -> None:
    now = [10.0]
    recovery = RecoveryController(now=lambda: now[0])
    assert recovery.push("event: message_start\n\n") == []

    now[0] = 100.0
    recovery.restart_holdback_deadline()
    now[0] += 0.75

    pending = asyncio.create_task(asyncio.sleep(60.0))
    try:
        assert not await recovery.event_arrived_before_holdback_deadline(pending)
        assert not pending.cancelled()
        assert recovery.flush() == ["event: message_start\n\n"]
        assert recovery.committed
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_holdback_wait_returns_immediately_after_commit() -> None:
    recovery = RecoveryController()
    assert recovery.push("event: message_start\n\n") == []
    assert recovery.flush() == ["event: message_start\n\n"]

    pending = asyncio.create_task(asyncio.sleep(0.01))
    try:
        assert await recovery.event_arrived_before_holdback_deadline(pending)
        assert not pending.cancelled()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
