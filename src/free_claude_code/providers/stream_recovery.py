"""Provider-owned stream holdback and recovery decisions."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

import httpx
import openai

from free_claude_code.core.failures import ExecutionFailure

from .failure_policy import RetryableProviderProtocolError, retryable_transient_status

EARLY_HOLDBACK_SECONDS = 0.75
RECOVERY_BUFFER_MAX_BYTES = 65_536

T = TypeVar("T")


class TruncatedProviderStreamError(RetryableProviderProtocolError):
    """An upstream stream ended without its required terminal marker."""


class RecoveryStreamSignal(StrEnum):
    """Control signal emitted while a held stream waits for upstream data."""

    HOLDBACK_DEADLINE = "holdback_deadline"


class RecoveryFailureAction(StrEnum):
    """How one provider stream should respond to an upstream failure."""

    EARLY_RETRY = "early_retry"
    MIDSTREAM_RECOVERY = "midstream_recovery"
    FINAL_ERROR = "final_error"


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """Failure decision for one provider stream attempt."""

    action: RecoveryFailureAction
    retryable: bool
    committed: bool
    has_buffered: bool


class RecoveryHoldbackBuffer:
    """Briefly retain SSE so early cutoffs can be retried invisibly."""

    def __init__(
        self,
        *,
        holdback_seconds: float = EARLY_HOLDBACK_SECONDS,
        max_bytes: int = RECOVERY_BUFFER_MAX_BYTES,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._holdback_seconds = holdback_seconds
        self._max_bytes = max_bytes
        self._now = now or time.monotonic
        self._events: list[str] = []
        self._bytes = 0
        self._started_at: float | None = None
        self.committed = False

    def push(self, event: str) -> list[str]:
        if self.committed:
            return [event]
        if self._started_at is None:
            self._started_at = self._now()
        self._events.append(event)
        self._bytes += len(event.encode("utf-8", errors="replace"))
        if (
            self._bytes >= self._max_bytes
            or self._now() - self._started_at >= self._holdback_seconds
        ):
            return self.flush()
        return []

    def restart_deadline(self) -> None:
        """Start the holdback clock from accepted upstream stream ownership."""
        if self.committed or not self._events:
            return
        self._started_at = self._now()

    def remaining_holdback_seconds(self) -> float | None:
        """Return wall-clock time left before buffered output must commit."""
        if self.committed or self._started_at is None:
            return None
        elapsed = self._now() - self._started_at
        return max(0.0, self._holdback_seconds - elapsed)

    def flush(self) -> list[str]:
        if self.committed:
            return []
        self.committed = True
        events = self._events
        self._events = []
        self._bytes = 0
        self._started_at = None
        return events

    def discard(self) -> None:
        self._events = []
        self._bytes = 0
        self._started_at = None

    @property
    def has_buffered(self) -> bool:
        return bool(self._events)


class RecoveryController:
    """Own commit-boundary holdback for one provider stream lifecycle."""

    def __init__(
        self,
        *,
        holdback_seconds: float = EARLY_HOLDBACK_SECONDS,
        max_bytes: int = RECOVERY_BUFFER_MAX_BYTES,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._holdback_seconds = holdback_seconds
        self._max_bytes = max_bytes
        self._now = now
        self._uses_default_holdback_config = (
            holdback_seconds == EARLY_HOLDBACK_SECONDS
            and max_bytes == RECOVERY_BUFFER_MAX_BYTES
            and now is None
        )
        self._holdback = self._new_holdback()

    def _new_holdback(self) -> RecoveryHoldbackBuffer:
        if self._uses_default_holdback_config:
            return RecoveryHoldbackBuffer()
        return RecoveryHoldbackBuffer(
            holdback_seconds=self._holdback_seconds,
            max_bytes=self._max_bytes,
            now=self._now,
        )

    @property
    def committed(self) -> bool:
        return self._holdback.committed

    @property
    def has_buffered(self) -> bool:
        return self._holdback.has_buffered

    def push(self, event: str) -> list[str]:
        return self._holdback.push(event)

    def restart_holdback_deadline(self) -> None:
        """Restart the holdback clock after upstream accepts the stream."""
        self._holdback.restart_deadline()

    async def iterate_with_holdback_deadline(
        self, source: AsyncIterator[T]
    ) -> AsyncIterator[T | RecoveryStreamSignal]:
        """Signal the deadline without cancelling the pending upstream read.

        After the caller flushes this controller, the same pending read is
        awaited to completion. Once committed, later items are forwarded
        directly without creating one task per token or event.
        """
        iterator = source.__aiter__()
        pending: asyncio.Future[T] | None = None
        try:
            while not self.committed:
                remaining = self._holdback.remaining_holdback_seconds()
                if remaining is None:
                    break
                if pending is None:
                    pending = asyncio.ensure_future(anext(iterator))
                done, _ = await asyncio.wait({pending}, timeout=remaining)
                if not done:
                    yield RecoveryStreamSignal.HOLDBACK_DEADLINE
                    if not self.committed:
                        raise RuntimeError(
                            "holdback deadline signal must be committed before resuming"
                        )
                    try:
                        yield await pending
                    except StopAsyncIteration:
                        return
                    pending = None
                    break
                try:
                    yield await pending
                except StopAsyncIteration:
                    return
                pending = None

            if pending is not None:
                try:
                    yield await pending
                except StopAsyncIteration:
                    return
                pending = None
            async for item in iterator:
                yield item
        finally:
            if pending is not None:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    def flush(self) -> list[str]:
        return self._holdback.flush()

    def discard(self) -> None:
        self._holdback.discard()

    def flush_uncommitted(self, decision: RecoveryDecision) -> list[str]:
        if not decision.committed and decision.has_buffered:
            return self.flush()
        return []

    def advance_failure(
        self,
        error: BaseException,
        *,
        stream_opened: bool,
        generated_output: bool,
        complete_tool_salvageable: bool,
        attempts_remaining: int,
        retryable_override: bool | None = None,
    ) -> RecoveryDecision:
        retryable = (
            is_retryable_stream_error(error)
            if retryable_override is None
            else retryable_override
        )
        committed = self._holdback.committed
        has_buffered = self._holdback.has_buffered
        retry_available = attempts_remaining > 0
        reserve_last_attempt_for_recovery = generated_output and attempts_remaining == 1

        if (
            retryable
            and retry_available
            and stream_opened
            and not committed
            and not complete_tool_salvageable
            and not reserve_last_attempt_for_recovery
        ):
            self._holdback.discard()
            self._holdback = self._new_holdback()
            return RecoveryDecision(
                action=RecoveryFailureAction.EARLY_RETRY,
                retryable=True,
                committed=False,
                has_buffered=has_buffered,
            )

        if (
            retryable
            and generated_output
            and (retry_available or complete_tool_salvageable)
        ):
            return RecoveryDecision(
                action=RecoveryFailureAction.MIDSTREAM_RECOVERY,
                retryable=True,
                committed=committed,
                has_buffered=has_buffered,
            )

        return RecoveryDecision(
            action=RecoveryFailureAction.FINAL_ERROR,
            retryable=retryable,
            committed=committed,
            has_buffered=has_buffered,
        )


def is_retryable_stream_error(exc: BaseException) -> bool:
    """Return whether one stream failure qualifies for retry or recovery."""
    if isinstance(exc, RetryableProviderProtocolError):
        return True
    if isinstance(exc, ExecutionFailure):
        return exc.retryable
    if isinstance(exc, openai.AuthenticationError | openai.BadRequestError):
        return False
    if retryable_transient_status(exc) is not None:
        return True
    return isinstance(
        exc,
        (
            TimeoutError,
            httpx.ReadTimeout,
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.NetworkError,
            openai.APITimeoutError,
            openai.APIConnectionError,
        ),
    )
