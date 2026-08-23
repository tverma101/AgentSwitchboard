"""Dedicated asynchronous Stop hook process for FCC Learning."""

import json
import os
import sys
from typing import Any

from .engine import learn_from_turn
from .store import LearningStore


def _read_hook_input() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def handle_stop(payload: dict[str, Any], store: LearningStore) -> None:
    """Distill one completed Claude Code turn when prompt state is available."""

    if payload.get("stop_hook_active"):
        return
    session_id = str(payload.get("session_id") or "")
    assistant_message = payload.get("last_assistant_message")
    if not isinstance(assistant_message, str) or not assistant_message.strip():
        return
    stored = store.prompt_for_session(session_id)
    if stored is None:
        return
    cwd, prompt = stored
    payload_cwd = payload.get("cwd")
    if isinstance(payload_cwd, str) and payload_cwd:
        cwd = payload_cwd
    learn_from_turn(
        cwd=cwd,
        user_prompt=prompt,
        assistant_message=assistant_message,
        store=store,
    )


def main() -> None:
    """Read Stop hook JSON from stdin without ever breaking Claude Code."""

    if os.environ.get("FCC_LEARNING_ENABLED", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return
    try:
        handle_stop(_read_hook_input(), LearningStore())
    except Exception as exc:
        print(f"FCC Learning Stop hook failed: {type(exc).__name__}", file=sys.stderr)


if __name__ == "__main__":
    main()
