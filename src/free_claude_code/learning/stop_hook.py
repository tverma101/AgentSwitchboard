"""Durable Stop-hook enqueue and short-lived FCC Learning worker."""

import json
import os
import subprocess
import sys
from typing import Any

from .engine import learn_from_turn
from .store import LearningStore

_WORKER_FLAG = "FCC_LEARNING_WORKER"


def _read_hook_input() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError, OSError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _attribution(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("fault_attribution")
    if isinstance(value, dict):
        return value
    fields = {
        key: payload[key]
        for key in ("fault_domain", "evidence_codes", "success", "confidence")
        if key in payload
    }
    return fields


def enqueue_stop(payload: dict[str, Any], store: LearningStore) -> str | None:
    """Persist the completed turn locally and return its deterministic queue id."""

    if payload.get("stop_hook_active"):
        return None
    session_id = str(payload.get("session_id") or "")
    assistant_message = payload.get("last_assistant_message")
    if not isinstance(assistant_message, str) or not assistant_message.strip():
        return None
    stored = store.prompt_for_session(session_id)
    if stored is None:
        return None
    cwd, prompt = stored
    payload_cwd = payload.get("cwd")
    if isinstance(payload_cwd, str) and payload_cwd:
        cwd = payload_cwd
    return store.enqueue_learning(
        session_id=session_id,
        cwd=cwd,
        user_prompt=prompt,
        assistant_message=assistant_message,
        attribution=_attribution(payload),
    )


def spawn_queue_worker() -> None:
    """Start one bounded worker process when stale queue work exists."""

    if os.environ.get(_WORKER_FLAG) == "1":
        return
    environment = os.environ.copy()
    environment[_WORKER_FLAG] = "1"
    try:
        subprocess.Popen(
            [sys.executable, "-m", "free_claude_code.learning.stop_hook", "--drain"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        )
    except OSError:
        return


def drain_queue(store: LearningStore, *, max_items: int = 2) -> int:
    """Process a bounded number of queue rows and exit; never becomes a daemon."""

    processed = 0
    for _ in range(max(0, max_items)):
        item = store.claim_learning()
        if item is None:
            break
        queue_id = str(item["queue_id"])
        try:
            attribution = json.loads(str(item.get("attribution_json") or "{}"))
            if not isinstance(attribution, dict):
                attribution = {}
            learn_from_turn(
                cwd=str(item["cwd"]),
                user_prompt=str(item["user_prompt"]),
                assistant_message=str(item["assistant_message"]),
                store=store,
                attribution=attribution,
            )
        except Exception as exc:
            store.fail_learning(
                queue_id,
                error=f"{type(exc).__name__}: {exc}",
                max_attempts=int(os.environ.get("FCC_LEARNING_MAX_ATTEMPTS", "3")),
            )
        else:
            store.complete_learning(queue_id)
        processed += 1
    store.cleanup_queue()
    return processed


def handle_stop(payload: dict[str, Any], store: LearningStore) -> None:
    """Enqueue one completed Claude Code turn and trigger best-effort draining."""

    queue_id = enqueue_stop(payload, store)
    if queue_id is not None:
        spawn_queue_worker()


def main() -> None:
    """Read Stop-hook JSON or drain a bounded queue without breaking Claude Code."""

    if os.environ.get("FCC_LEARNING_ENABLED", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return
    try:
        store = LearningStore()
        if "--drain" in sys.argv[1:]:
            drain_queue(
                store, max_items=int(os.environ.get("FCC_LEARNING_DRAIN_LIMIT", "2"))
            )
            return
        handle_stop(_read_hook_input(), store)
    except Exception as exc:
        print(f"FCC Learning Stop hook failed: {type(exc).__name__}", file=sys.stderr)


if __name__ == "__main__":
    main()
