"""Claude SessionEnd hook for bounded session-evidence reconciliation."""

import json
import os
import sys
from typing import Any

from .config import learning_enabled
from .hooks import claude_config_dir
from .session_evidence import recover_queued_human_steers
from .session_ledger import SessionEvidenceLedger
from .store import LearningStore


def _read_hook_input() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError, OSError:
        return {}
    return payload if isinstance(payload, dict) else {}


def handle_session_end(payload: dict[str, Any], store: LearningStore) -> None:
    """Persist only sanitized evidence proven safe at the real session boundary."""

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    cwd_value = payload.get("cwd")
    cwd = cwd_value if isinstance(cwd_value, str) and cwd_value else os.getcwd()
    transcript = payload.get("transcript_path")
    ledger = SessionEvidenceLedger(store)

    if not isinstance(transcript, str) or not transcript:
        ledger.record_session_end(
            session_id=session_id,
            cwd=cwd,
            transcript_complete=False,
            transcript_reason="missing_transcript_path",
        )
        return

    recovered = recover_queued_human_steers(
        transcript,
        session_id=session_id,
        claude_config_dir=claude_config_dir(),
    )
    if recovered.complete:
        for steer in recovered.steers:
            ledger.record(
                session_id=session_id,
                kind="human_steer",
                text=steer.text,
                source_id=steer.source_id,
                metadata={
                    "source": "claude_transcript_queued_command",
                    "timestamp": steer.timestamp,
                },
            )
    ledger.record_session_end(
        session_id=session_id,
        cwd=cwd,
        transcript_complete=recovered.complete,
        transcript_reason=recovered.reason,
    )


def main() -> None:
    """Read one SessionEnd payload without ever persisting the raw transcript."""

    if not learning_enabled():
        return
    try:
        handle_session_end(_read_hook_input(), LearningStore())
    except Exception as exc:
        print(
            f"FCC Learning SessionEnd hook failed: {type(exc).__name__}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
