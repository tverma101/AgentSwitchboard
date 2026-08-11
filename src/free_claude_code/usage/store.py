"""SQLite-backed usage ledger used by the local Admin UI."""

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

_TOKEN_COLUMNS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "web_search_requests",
    "web_fetch_requests",
)


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """One completed or failed provider-backed request."""

    request_id: str
    occurred_at: datetime
    provider_id: str
    model: str
    wire_api: str
    status: str
    duration_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    web_search_requests: int = 0
    web_fetch_requests: int = 0
    error_type: str | None = None


class UsageStore:
    """Persist usage events without retaining prompt or response content."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()
        self._initialize()

    def record(self, event: UsageEvent) -> None:
        """Insert or replace one request's final usage record."""
        occurred_at = _as_utc(event.occurred_at)
        local_day = occurred_at.astimezone().date().isoformat()
        values = (
            event.request_id,
            occurred_at.isoformat(),
            local_day,
            event.provider_id,
            event.model,
            event.wire_api,
            event.status,
            max(0, event.duration_ms),
            *(_non_negative_int(getattr(event, key)) for key in _TOKEN_COLUMNS),
            event.error_type,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO usage_events (
                    request_id, occurred_at, local_day, provider_id, model,
                    wire_api, status, duration_ms, input_tokens, output_tokens,
                    cache_read_input_tokens, cache_creation_input_tokens,
                    web_search_requests, web_fetch_requests, error_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    occurred_at=excluded.occurred_at,
                    local_day=excluded.local_day,
                    provider_id=excluded.provider_id,
                    model=excluded.model,
                    wire_api=excluded.wire_api,
                    status=excluded.status,
                    duration_ms=excluded.duration_ms,
                    input_tokens=excluded.input_tokens,
                    output_tokens=excluded.output_tokens,
                    cache_read_input_tokens=excluded.cache_read_input_tokens,
                    cache_creation_input_tokens=excluded.cache_creation_input_tokens,
                    web_search_requests=excluded.web_search_requests,
                    web_fetch_requests=excluded.web_fetch_requests,
                    error_type=excluded.error_type
                """,
                values,
            )

    def summary(self, days: int = 30, *, now: datetime | None = None) -> dict[str, Any]:
        """Return totals, local-day buckets, and model totals for the UI."""
        if not 1 <= days <= 366:
            raise ValueError("days must be between 1 and 366")
        end_day = _as_local_date(now or datetime.now(UTC))
        start_day = end_day - timedelta(days=days - 1)
        params = (start_day.isoformat(), end_day.isoformat())
        with self._lock, self._connect() as connection:
            daily_rows = connection.execute(
                """
                SELECT local_day, COUNT(*),
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END),
                       SUM(input_tokens), SUM(output_tokens),
                       SUM(cache_read_input_tokens),
                       SUM(cache_creation_input_tokens),
                       SUM(web_search_requests), SUM(web_fetch_requests)
                FROM usage_events
                WHERE local_day BETWEEN ? AND ?
                GROUP BY local_day
                ORDER BY local_day
                """,
                params,
            ).fetchall()
            model_rows = connection.execute(
                """
                SELECT provider_id, model, COUNT(*),
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END),
                       SUM(input_tokens), SUM(output_tokens),
                       SUM(cache_read_input_tokens),
                       SUM(cache_creation_input_tokens)
                FROM usage_events
                WHERE local_day BETWEEN ? AND ?
                GROUP BY provider_id, model
                ORDER BY (SUM(input_tokens) + SUM(output_tokens)) DESC, model
                """,
                params,
            ).fetchall()

        daily_by_day = {row[0]: _bucket_from_row(row) for row in daily_rows}
        daily = []
        current = start_day
        while current <= end_day:
            day = current.isoformat()
            daily.append({"date": day, **daily_by_day.get(day, _empty_bucket())})
            current += timedelta(days=1)

        totals = _empty_bucket()
        for bucket in daily:
            for key in totals:
                totals[key] += int(bucket[key])

        models = [
            {
                "provider_id": row[0],
                "model": row[1],
                "requests": row[2] or 0,
                "successful_requests": row[3] or 0,
                "failed_requests": row[4] or 0,
                "input_tokens": row[5] or 0,
                "output_tokens": row[6] or 0,
                "cache_read_input_tokens": row[7] or 0,
                "cache_creation_input_tokens": row[8] or 0,
            }
            for row in model_rows
        ]
        return {
            "range_days": days,
            "from": start_day.isoformat(),
            "to": end_day.isoformat(),
            "totals": totals,
            "daily": daily,
            "models": models,
        }

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    request_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    local_day TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    wire_api TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
                    web_search_requests INTEGER NOT NULL DEFAULT 0,
                    web_fetch_requests INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS usage_events_day_idx ON usage_events(local_day)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS usage_events_model_idx ON usage_events(provider_id, model)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection


def _empty_bucket() -> dict[str, int]:
    return {
        "requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "web_search_requests": 0,
        "web_fetch_requests": 0,
    }


def _bucket_from_row(row: tuple[Any, ...]) -> dict[str, int]:
    return {
        "requests": int(row[1] or 0),
        "successful_requests": int(row[2] or 0),
        "failed_requests": int(row[3] or 0),
        "input_tokens": int(row[4] or 0),
        "output_tokens": int(row[5] or 0),
        "cache_read_input_tokens": int(row[6] or 0),
        "cache_creation_input_tokens": int(row[7] or 0),
        "web_search_requests": int(row[8] or 0),
        "web_fetch_requests": int(row[9] or 0),
    }


def _non_negative_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return 0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_local_date(value: datetime) -> date:
    return _as_utc(value).astimezone().date()
