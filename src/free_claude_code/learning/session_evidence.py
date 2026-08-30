"""Ephemeral, fail-closed recovery of human steering from Claude transcripts."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import redact_sensitive

MAX_TRANSCRIPT_BYTES = 64 * 1024 * 1024
MAX_TRANSCRIPT_LINE_BYTES = 4 * 1024 * 1024
MAX_HUMAN_STEERS = 24
MAX_STEER_CHARS = 8_000


@dataclass(frozen=True, slots=True)
class HumanSteer:
    """One structurally proven human mid-run instruction."""

    source_id: str
    text: str
    timestamp: str = ""


@dataclass(frozen=True, slots=True)
class TranscriptHumanEvidence:
    """Sanitized human steering plus whether transcript reconciliation was sound."""

    steers: tuple[HumanSteer, ...]
    complete: bool
    reason: str


def _truncate(text: str, limit: int) -> str:
    value = " ".join(text.split()).strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 14)].rstrip() + "...[truncated]"


def _trusted_transcript(
    transcript_path: str | Path,
    *,
    claude_config_dir: str | Path,
) -> tuple[Path | None, str]:
    """Resolve a transcript only when it stays below Claude's projects tree."""

    try:
        projects_root = (Path(claude_config_dir).expanduser() / "projects").resolve(
            strict=True
        )
        candidate = Path(transcript_path).expanduser().resolve(strict=True)
    except OSError:
        return None, "unreadable_path"
    if not candidate.is_relative_to(projects_root):
        return None, "outside_claude_projects"
    if candidate.suffix != ".jsonl" or not candidate.is_file():
        return None, "not_claude_jsonl"
    try:
        size = candidate.stat().st_size
    except OSError:
        return None, "unreadable_path"
    if size > MAX_TRANSCRIPT_BYTES:
        return None, "transcript_too_large"
    return candidate, "ok"


def _record_session_matches(record: dict[str, Any], session_id: str) -> bool:
    observed = record.get("sessionId", record.get("session_id"))
    return not isinstance(observed, str) or not observed or observed == session_id


def _human_queued_command(record: dict[str, Any]) -> tuple[str, str] | None:
    """Return (prompt, timestamp) only for positive human provenance markers."""

    if record.get("type") != "attachment" or record.get("isSidechain") is True:
        return None
    user_type = record.get("userType")
    if isinstance(user_type, str) and user_type != "external":
        return None
    attachment = record.get("attachment")
    if not isinstance(attachment, dict):
        return None
    if attachment.get("type") != "queued_command":
        return None
    if attachment.get("commandMode") != "prompt":
        return None
    if attachment.get("isMeta") is True or record.get("isMeta") is True:
        return None
    # Current transcript consumers use absence of origin as part of the positive
    # human marker. Internal/task notifications may use the same attachment type.
    if "origin" in attachment:
        return None
    prompt = attachment.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    timestamp = record.get("timestamp")
    return prompt, timestamp if isinstance(timestamp, str) else ""


def recover_queued_human_steers(
    transcript_path: str | Path,
    *,
    session_id: str,
    claude_config_dir: str | Path,
    max_items: int = MAX_HUMAN_STEERS,
) -> TranscriptHumanEvidence:
    """Ephemerally scan Claude JSONL and return only proven queued human prompts.

    Raw transcript records are never returned. Any malformed non-empty record,
    oversized line, invalid UTF-8, or untrusted path makes the reconciliation
    incomplete and returns no steering at all.
    """

    if not session_id:
        return TranscriptHumanEvidence((), False, "missing_session_id")
    candidate, reason = _trusted_transcript(
        transcript_path,
        claude_config_dir=claude_config_dir,
    )
    if candidate is None:
        return TranscriptHumanEvidence((), False, reason)

    recovered: list[HumanSteer] = []
    seen: set[str] = set()
    try:
        with candidate.open("rb") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if len(raw_line) > MAX_TRANSCRIPT_LINE_BYTES:
                    return TranscriptHumanEvidence((), False, "line_too_large")
                if not raw_line.strip():
                    continue
                try:
                    text_line = raw_line.decode("utf-8", errors="strict")
                    value = json.loads(text_line)
                except UnicodeDecodeError, json.JSONDecodeError:
                    return TranscriptHumanEvidence((), False, "malformed_jsonl")
                if not isinstance(value, dict):
                    return TranscriptHumanEvidence((), False, "malformed_jsonl")
                if not _record_session_matches(value, session_id):
                    continue
                human = _human_queued_command(value)
                if human is None:
                    continue
                prompt, timestamp = human
                attachment = value.get("attachment")
                source_hint = (
                    attachment.get("source_uuid")
                    if isinstance(attachment, dict)
                    else None
                )
                if not isinstance(source_hint, str) or not source_hint:
                    record_uuid = value.get("uuid")
                    source_hint = record_uuid if isinstance(record_uuid, str) else ""
                clean = _truncate(redact_sensitive(prompt), MAX_STEER_CHARS)
                if not clean:
                    continue
                if source_hint:
                    source_id = source_hint
                else:
                    source_id = hashlib.sha256(
                        f"{session_id}\0{line_number}\0{timestamp}\0{clean}".encode()
                    ).hexdigest()
                if source_id in seen:
                    continue
                seen.add(source_id)
                recovered.append(HumanSteer(source_id, clean, timestamp))
    except OSError:
        return TranscriptHumanEvidence((), False, "read_failed")

    limit = max(0, max_items)
    if limit == 0:
        recovered = []
    elif len(recovered) > limit:
        recovered = recovered[-limit:]
    return TranscriptHumanEvidence(tuple(recovered), True, "ok")


__all__ = [
    "HumanSteer",
    "MAX_HUMAN_STEERS",
    "MAX_STEER_CHARS",
    "MAX_TRANSCRIPT_BYTES",
    "MAX_TRANSCRIPT_LINE_BYTES",
    "TranscriptHumanEvidence",
    "recover_queued_human_steers",
]
