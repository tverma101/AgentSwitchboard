"""SQLite-backed usage ledger used by the local Admin UI."""

import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

FCC_USAGE_SOURCE = "fcc_proxy"
AccountFingerprintResolver = Callable[[str], str | None]

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
    source: str = FCC_USAGE_SOURCE
    account_fingerprint: str | None = None


class UsageStore:
    """Persist usage events without retaining prompt or response content."""

    def __init__(
        self,
        path: str | Path,
        *,
        account_fingerprint_resolver: AccountFingerprintResolver | None = None,
    ):
        self.path = Path(path).expanduser()
        self._account_fingerprint_resolver = account_fingerprint_resolver
        self._lock = threading.Lock()
        self._initialize()

    def record(self, event: UsageEvent) -> None:
        """Insert or replace one request's final usage record."""
        occurred_at = _as_utc(event.occurred_at)
        local_day = occurred_at.astimezone().date().isoformat()
        source = _normalize_source(event.source)
        account_fingerprint = _normalize_account_fingerprint(event.account_fingerprint)
        if (
            account_fingerprint is None
            and self._account_fingerprint_resolver is not None
        ):
            try:
                account_fingerprint = _normalize_account_fingerprint(
                    self._account_fingerprint_resolver(event.provider_id)
                )
            except Exception:
                # Attribution is additive metadata. A stale or unavailable
                # account manager must never discard the usage event itself.
                account_fingerprint = None
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
            source,
            account_fingerprint,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO usage_events (
                    request_id, occurred_at, local_day, provider_id, model,
                    wire_api, status, duration_ms, input_tokens, output_tokens,
                    cache_read_input_tokens, cache_creation_input_tokens,
                    web_search_requests, web_fetch_requests, error_type,
                    source, account_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    error_type=excluded.error_type,
                    source=excluded.source,
                    account_fingerprint=excluded.account_fingerprint
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
                SELECT provider_id, model, wire_api, source, account_fingerprint,
                       COUNT(*),
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END),
                       SUM(input_tokens), SUM(output_tokens),
                       SUM(cache_read_input_tokens),
                       SUM(cache_creation_input_tokens)
                FROM usage_events
                WHERE local_day BETWEEN ? AND ?
                GROUP BY provider_id, model, wire_api, source, account_fingerprint
                ORDER BY (SUM(input_tokens) + SUM(output_tokens)) DESC,
                         provider_id, model, wire_api, source,
                         account_fingerprint
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

        models = [_model_usage_row(row) for row in model_rows]
        return {
            "range_days": days,
            "from": start_day.isoformat(),
            "to": end_day.isoformat(),
            "totals": totals,
            "daily": daily,
            "models": models,
            "tracking": tracking_summary(),
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
                    error_type TEXT,
                    source TEXT NOT NULL DEFAULT 'fcc_proxy',
                    account_fingerprint TEXT
                )
                """
            )
            _ensure_column(
                connection,
                "usage_events",
                "source",
                "TEXT NOT NULL DEFAULT 'fcc_proxy'",
            )
            _ensure_column(
                connection,
                "usage_events",
                "account_fingerprint",
                "TEXT",
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS usage_events_day_idx ON usage_events(local_day)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS usage_events_model_idx ON usage_events(provider_id, model)"
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS usage_events_tracking_idx
                ON usage_events(source, account_fingerprint, wire_api)
                """
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


def _model_usage_row(row: tuple[Any, ...]) -> dict[str, Any]:
    source = _normalize_source(row[3])
    wire_api = str(row[2] or "unknown")
    account_fingerprint = _normalize_account_fingerprint(row[4])
    return {
        "provider_id": row[0],
        "model": row[1],
        "wire_api": wire_api,
        "wire_api_label": _wire_api_label(wire_api),
        "source": source,
        "source_label": _source_label(source),
        "account_fingerprint": account_fingerprint,
        "account_label": _account_label(account_fingerprint),
        "tracking_label": _tracking_label(
            source,
            wire_api,
            account_fingerprint,
        ),
        "requests": row[5] or 0,
        "successful_requests": row[6] or 0,
        "failed_requests": row[7] or 0,
        "input_tokens": row[8] or 0,
        "output_tokens": row[9] or 0,
        "cache_read_input_tokens": row[10] or 0,
        "cache_creation_input_tokens": row[11] or 0,
    }


def tracking_summary() -> dict[str, str]:
    """Describe FCC's usage-attribution and content-retention contract."""

    return {
        "source": FCC_USAGE_SOURCE,
        "source_label": _source_label(FCC_USAGE_SOURCE),
        "account_labeling": "Per-event privacy-preserving account fingerprint when available",
        "content_policy": "Metadata only; prompts and responses are never stored",
        "native_codex_usage": "Tracked separately from the FCC proxy ledger",
    }


def _source_label(source: str) -> str:
    if source == FCC_USAGE_SOURCE:
        return "FCC proxy"
    return source.replace("_", " ").strip().title() or "Unknown source"


def _wire_api_label(wire_api: str) -> str:
    return {
        "messages": "Anthropic Messages",
        "responses": "OpenAI Responses",
    }.get(wire_api, wire_api.replace("_", " ").strip().title() or "Unknown API")


def _account_label(account_fingerprint: str | None) -> str:
    if account_fingerprint is None:
        return "Account not identified"
    return f"Account {account_fingerprint}"


def _tracking_label(
    source: str,
    wire_api: str,
    account_fingerprint: str | None,
) -> str:
    return " · ".join(
        (
            _source_label(source),
            _wire_api_label(wire_api),
            _account_label(account_fingerprint),
        )
    )


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_ACCOUNT_FINGERPRINT_RE = re.compile(r"^acct_[0-9a-f]{12}$")


def _normalize_source(value: Any) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if _IDENTIFIER_RE.fullmatch(candidate):
            return candidate
    return FCC_USAGE_SOURCE


def _normalize_account_fingerprint(value: Any) -> str | None:
    if isinstance(value, str) and _ACCOUNT_FINGERPRINT_RE.fullmatch(value.strip()):
        return value.strip()
    return None


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
