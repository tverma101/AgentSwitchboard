"""Incremental extraction of final Anthropic usage from an internal SSE stream."""

import json
from datetime import UTC, datetime
from time import monotonic

from loguru import logger

from .store import UsageEvent, UsageStore


class UsageStreamObserver:
    """Observe public usage events without buffering prompt or response content."""

    def __init__(
        self,
        store: UsageStore,
        *,
        request_id: str,
        provider_id: str,
        model: str,
        wire_api: str,
    ) -> None:
        self._store = store
        self._request_id = request_id
        self._provider_id = provider_id
        self._model = model
        self._wire_api = wire_api
        self._started_at = monotonic()
        self._occurred_at = datetime.now(UTC)
        self._buffer = ""
        self._usage: dict[str, int] = {}
        self._completed = False
        self._error_type: str | None = None
        self._recorded = False

    def feed(self, chunk: str | bytes) -> None:
        """Consume one stream chunk and retain only numeric usage fields."""
        self._buffer += (
            chunk.decode("utf-8", errors="replace")
            if isinstance(chunk, bytes)
            else str(chunk)
        )
        self._buffer = self._buffer.replace("\r\n", "\n")
        while "\n\n" in self._buffer:
            raw, self._buffer = self._buffer.split("\n\n", 1)
            self._consume_event(raw)

    def finish(self, error: BaseException | None = None) -> None:
        """Write one final record; accounting failures never break the request."""
        if self._recorded:
            return
        if self._buffer.strip():
            self._consume_event(self._buffer)
        self._recorded = True
        status = "success" if error is None and self._completed else "error"
        error_type = self._error_type or (type(error).__name__ if error else None)
        event = UsageEvent(
            request_id=self._request_id,
            occurred_at=self._occurred_at,
            provider_id=self._provider_id,
            model=self._model,
            wire_api=self._wire_api,
            status=status,
            duration_ms=round((monotonic() - self._started_at) * 1000),
            input_tokens=self._usage.get("input_tokens", 0),
            output_tokens=self._usage.get("output_tokens", 0),
            cache_read_input_tokens=self._usage.get("cache_read_input_tokens", 0),
            cache_creation_input_tokens=self._usage.get(
                "cache_creation_input_tokens", 0
            ),
            web_search_requests=self._usage.get("web_search_requests", 0),
            web_fetch_requests=self._usage.get("web_fetch_requests", 0),
            error_type=error_type,
        )
        try:
            self._store.record(event)
        except Exception as exc:
            logger.warning("Usage ledger write failed: exc_type={}", type(exc).__name__)

    def _consume_event(self, raw: str) -> None:
        event_name = ""
        data_parts: list[str] = []
        for line in raw.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_parts.append(line.split(":", 1)[1].strip())
        if not event_name and not data_parts:
            return
        try:
            data = json.loads("\n".join(data_parts)) if data_parts else {}
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        usage = data.get("usage")
        if isinstance(usage, dict):
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    self._usage[key] = max(0, value)
            server_tool_use = usage.get("server_tool_use")
            if isinstance(server_tool_use, dict):
                for key in ("web_search_requests", "web_fetch_requests"):
                    value = server_tool_use.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        self._usage[key] = max(0, value)
        if event_name in {"message_stop", "response.completed"}:
            self._completed = True
        if event_name == "error":
            error = data.get("error")
            if isinstance(error, dict) and isinstance(error.get("type"), str):
                self._error_type = error["type"]
