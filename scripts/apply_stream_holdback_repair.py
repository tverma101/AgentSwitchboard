from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


path = Path("src/free_claude_code/providers/stream_recovery.py")
text = path.read_text()
text = replace_once(
    text,
    "import time\nfrom collections.abc import Callable\nfrom dataclasses import dataclass\nfrom enum import StrEnum\n",
    "import asyncio\nimport time\nfrom collections.abc import AsyncIterator, Callable\nfrom dataclasses import dataclass\nfrom enum import StrEnum\nfrom typing import TypeVar\n",
    "stream recovery imports",
)
text = replace_once(
    text,
    "RECOVERY_BUFFER_MAX_BYTES = 65_536\n\n\nclass TruncatedProviderStreamError",
    "RECOVERY_BUFFER_MAX_BYTES = 65_536\n\nT = TypeVar(\"T\")\n\n\nclass TruncatedProviderStreamError",
    "stream recovery typevar",
)
text = replace_once(
    text,
    "class RecoveryFailureAction(StrEnum):\n",
    "class RecoveryStreamSignal(StrEnum):\n"
    "    \"\"\"Control signal emitted while a held stream waits for upstream data.\"\"\"\n\n"
    "    HOLDBACK_DEADLINE = \"holdback_deadline\"\n\n\n"
    "class RecoveryFailureAction(StrEnum):\n",
    "stream signal enum",
)
text = replace_once(
    text,
    """    def flush(self) -> list[str]:
        if self.committed:
            return []
""",
    """    def restart_deadline(self) -> None:
        \"\"\"Start the holdback clock from accepted upstream stream ownership.\"\"\"
        if self.committed or not self._events:
            return
        self._started_at = self._now()

    def remaining_holdback_seconds(self) -> float | None:
        \"\"\"Return wall-clock time left before buffered output must commit.\"\"\"
        if self.committed or self._started_at is None:
            return None
        elapsed = self._now() - self._started_at
        return max(0.0, self._holdback_seconds - elapsed)

    def flush(self) -> list[str]:
        if self.committed:
            return []
""",
    "holdback deadline methods",
)
text = replace_once(
    text,
    """class RecoveryController:
    \"\"\"Own commit-boundary holdback for one provider stream lifecycle.\"\"\"

    def __init__(self) -> None:
        self._holdback = RecoveryHoldbackBuffer()
""",
    """class RecoveryController:
    \"\"\"Own commit-boundary holdback for one provider stream lifecycle.\"\"\"

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
        self._holdback = self._new_holdback()

    def _new_holdback(self) -> RecoveryHoldbackBuffer:
        return RecoveryHoldbackBuffer(
            holdback_seconds=self._holdback_seconds,
            max_bytes=self._max_bytes,
            now=self._now,
        )
""",
    "controller constructor",
)
text = replace_once(
    text,
    """    def push(self, event: str) -> list[str]:
        return self._holdback.push(event)

    def flush(self) -> list[str]:
""",
    """    def push(self, event: str) -> list[str]:
        return self._holdback.push(event)

    def restart_holdback_deadline(self) -> None:
        \"\"\"Restart the holdback clock after upstream accepts the stream.\"\"\"
        self._holdback.restart_deadline()

    async def iterate_with_holdback_deadline(
        self, source: AsyncIterator[T]
    ) -> AsyncIterator[T | RecoveryStreamSignal]:
        \"\"\"Signal the deadline without cancelling the pending upstream read.

        After the caller flushes this controller, the same pending read is
        awaited to completion. Once committed, later items are forwarded
        directly without creating one task per token or event.
        \"\"\"
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
                            \"holdback deadline signal must be committed before resuming\"
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
""",
    "controller deadline iterator",
)
text = replace_once(
    text,
    "            self._holdback = RecoveryHoldbackBuffer()\n",
    "            self._holdback = self._new_holdback()\n",
    "holdback recreation",
)
path.write_text(text)


path = Path("src/free_claude_code/providers/openai_codex/provider.py")
text = path.read_text()
text = replace_once(
    text,
    "from free_claude_code.providers.stream_recovery import RecoveryController\n",
    "from free_claude_code.providers.stream_recovery import (\n"
    "    RecoveryController,\n"
    "    RecoveryStreamSignal,\n"
    ")\n",
    "codex recovery import",
)
text = replace_once(
    text,
    """                stream_opened = True

                async for event_type, payload in _iter_sse(response):
                    if not attempt.accepted:
                        await attempt.succeeded()
""",
    """                stream_opened = True
                recovery.restart_holdback_deadline()

                async for item in recovery.iterate_with_holdback_deadline(
                    _iter_sse(response)
                ):
                    if item is RecoveryStreamSignal.HOLDBACK_DEADLINE:
                        for held in recovery.flush():
                            yield held
                        continue
                    event_type, payload = item
                    if not attempt.accepted:
                        await attempt.succeeded()
""",
    "codex deadline iteration",
)
text = replace_once(
    text,
    """                if attempt is not None and not attempt.accepted:
                    await attempt.retry(error)
""",
    """                if (
                    attempt is not None
                    and not attempt.accepted
                    and not recovery.committed
                ):
                    await attempt.retry(error)
""",
    "codex committed retry guard",
)
path.write_text(text)


path = Path("src/free_claude_code/providers/openai_chat/provider.py")
text = path.read_text()
text = replace_once(
    text,
    """    RecoveryController,
    RecoveryFailureAction,
    TruncatedProviderStreamError,
""",
    """    RecoveryController,
    RecoveryFailureAction,
    RecoveryStreamSignal,
    TruncatedProviderStreamError,
""",
    "chat recovery import",
)
text = replace_once(
    text,
    """                stream_opened = True
                tool_argument_aliases = self._provider._tool_argument_aliases(body)
                async for chunk in stream:
                    if not attempt.accepted:
                        await attempt.succeeded()
""",
    """                stream_opened = True
                recovery.restart_holdback_deadline()
                tool_argument_aliases = self._provider._tool_argument_aliases(body)
                async for chunk in recovery.iterate_with_holdback_deadline(stream):
                    if chunk is RecoveryStreamSignal.HOLDBACK_DEADLINE:
                        for held in recovery.flush():
                            yield held
                        continue
                    if not attempt.accepted:
                        await attempt.succeeded()
""",
    "chat deadline iteration",
)
text = replace_once(
    text,
    """                if attempt is not None and not attempt.accepted:
                    await attempt.retry(
                        error,
                        provider_failure_override=(
                            self._provider._provider_failure_override
                        ),
                    )
                generated_output = has_committed_sse_output(ledger)
""",
    """                if (
                    attempt is not None
                    and not attempt.accepted
                    and not recovery.committed
                ):
                    await attempt.retry(
                        error,
                        provider_failure_override=(
                            self._provider._provider_failure_override
                        ),
                    )
                generated_output = has_committed_sse_output(ledger)
""",
    "chat primary committed retry guard",
)
path.write_text(text)


path = Path("src/free_claude_code/providers/opencode_go/provider.py")
text = path.read_text()
text = replace_once(
    text,
    "from free_claude_code.providers.stream_recovery import RecoveryController\n",
    "from free_claude_code.providers.stream_recovery import (\n"
    "    RecoveryController,\n"
    "    RecoveryStreamSignal,\n"
    ")\n",
    "go recovery import",
)
text = replace_once(
    text,
    """                        for ready_event in ready_events:
                            yield ready_event
                    async for event in upstream:
                        if not attempt.accepted:
                            await attempt.succeeded()
""",
    """                        for ready_event in ready_events:
                            yield ready_event
                    recovery.restart_holdback_deadline()
                    async for event in recovery.iterate_with_holdback_deadline(upstream):
                        if event is RecoveryStreamSignal.HOLDBACK_DEADLINE:
                            for ready_event in recovery.flush():
                                evidence.output_committed = True
                                if evidence.time_to_first_token_ms is None:
                                    evidence.time_to_first_token_ms = max(
                                        0, round((monotonic() - started_at) * 1000)
                                    )
                                yield ready_event
                            continue
                        if not attempt.accepted:
                            await attempt.succeeded()
""",
    "go deadline iteration",
)
text = replace_once(
    text,
    """                    if attempt is not None and not attempt.accepted:
                        should_retry = await attempt.retry(error)
""",
    """                    if (
                        attempt is not None
                        and not attempt.accepted
                        and not recovery.committed
                    ):
                        should_retry = await attempt.retry(error)
""",
    "go committed retry guard",
)
path.write_text(text)
