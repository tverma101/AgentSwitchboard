"""Bounded supporting evidence for session-level FCC Learning decisions."""

import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .store import LearningStore, redact_sensitive

_ALLOWED_KINDS = frozenset({"human_prompt", "human_steer", "turn_result"})
_KIND_LIMITS = {
    "human_prompt": 24,
    "human_steer": 24,
    "turn_result": 48,
}
_TEXT_LIMIT = 8_000
_METADATA_LIMIT = 4_000


@dataclass(frozen=True, slots=True)
class SessionEvidence:
    event_id: str
    session_id: str
    kind: str
    text: str
    source_id: str
    metadata_json: str
    created_at: float


class SessionEvidenceLedger:
    """Small session-evidence tables inside the existing Learning SQLite DB."""

    def __init__(self, store: LearningStore) -> None:
        self.store = store
        self.path = store.path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS session_evidence (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(
                        kind IN ('human_prompt', 'human_steer', 'turn_result')
                    ),
                    text TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_session_evidence_session_time
                ON session_evidence(session_id, created_at, event_id);

                CREATE TABLE IF NOT EXISTS session_end_state (
                    session_id TEXT PRIMARY KEY,
                    cwd TEXT NOT NULL,
                    transcript_complete INTEGER NOT NULL DEFAULT 0,
                    transcript_reason TEXT NOT NULL DEFAULT '',
                    ended_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _clean_text(text: str) -> str:
        value = " ".join(redact_sensitive(text).split()).strip()
        if len(value) <= _TEXT_LIMIT:
            return value
        return value[: _TEXT_LIMIT - 14].rstrip() + "...[truncated]"

    @staticmethod
    def _metadata(value: Mapping[str, Any] | None) -> str:
        try:
            encoded = json.dumps(
                dict(value or {}),
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except TypeError, ValueError:
            encoded = "{}"
        encoded = redact_sensitive(encoded)
        if len(encoded) > _METADATA_LIMIT:
            return json.dumps({"truncated": True}, separators=(",", ":"))
        return encoded

    def record(
        self,
        *,
        session_id: str,
        kind: str,
        text: str,
        source_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> str | None:
        """Insert one idempotent sanitized event and enforce a per-kind cap."""

        if not session_id or kind not in _ALLOWED_KINDS:
            return None
        clean = self._clean_text(text)
        if not clean:
            return None
        source = source_id.strip()
        if not source:
            source = hashlib.sha256(
                f"{session_id}\0{kind}\0{clean}".encode()
            ).hexdigest()
        event_id = hashlib.sha256(
            f"{session_id}\0{kind}\0{source}".encode()
        ).hexdigest()
        now = time.time()
        metadata_json = self._metadata(metadata)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO session_evidence(
                    event_id, session_id, kind, text, source_id,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    kind,
                    clean,
                    source,
                    metadata_json,
                    now,
                ),
            )
            limit = _KIND_LIMITS[kind]
            connection.execute(
                """
                DELETE FROM session_evidence
                WHERE event_id IN (
                    SELECT event_id FROM session_evidence
                    WHERE session_id = ? AND kind = ?
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (session_id, kind, limit),
            )
        return event_id

    def list_evidence(self, session_id: str) -> list[SessionEvidence]:
        if not session_id:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM session_evidence
                WHERE session_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            SessionEvidence(
                event_id=str(row["event_id"]),
                session_id=str(row["session_id"]),
                kind=str(row["kind"]),
                text=str(row["text"]),
                source_id=str(row["source_id"]),
                metadata_json=str(row["metadata_json"]),
                created_at=float(row["created_at"]),
            )
            for row in rows
        ]

    def record_session_end(
        self,
        *,
        session_id: str,
        cwd: str,
        transcript_complete: bool,
        transcript_reason: str,
    ) -> None:
        if not session_id:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO session_end_state(
                    session_id, cwd, transcript_complete,
                    transcript_reason, ended_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    cwd = excluded.cwd,
                    transcript_complete = excluded.transcript_complete,
                    transcript_reason = excluded.transcript_reason,
                    ended_at = excluded.ended_at
                """,
                (
                    session_id,
                    cwd,
                    int(transcript_complete),
                    transcript_reason[:200],
                    time.time(),
                ),
            )

    def session_end_state(self, session_id: str) -> dict[str, Any] | None:
        if not session_id:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM session_end_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row is not None else None


__all__ = ["SessionEvidence", "SessionEvidenceLedger"]
