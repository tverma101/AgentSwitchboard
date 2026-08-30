"""Neutral delegated-worker events for reviewer and learning integration.

Claude Code's Agent/Subagent hook payloads are adapter inputs, not the schema
owned by FCC's reviewer/learning core. Other worker implementations can emit the
same normalized event without copying Claude-specific JSON shapes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class WorkerLifecycle(StrEnum):
    """Lifecycle states relevant to bounded reviewer/learning behavior."""

    BACKGROUND = "background"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class DelegatedWorkerEvent:
    """Normalized metadata/result for one delegated worker transition."""

    source: str
    lifecycle: WorkerLifecycle
    task_input: Mapping[str, object]
    parent_session_id: str = ""
    worker_id: str = ""
    result_text: str = ""


def claude_agent_posttool_event(
    payload: Mapping[str, object],
) -> DelegatedWorkerEvent | None:
    """Adapt one Claude Code Agent PostToolUse payload to the neutral contract."""

    if payload.get("tool_name") != "Agent":
        return None
    raw_input = payload.get("tool_input")
    raw_response = payload.get("tool_response")
    if not isinstance(raw_input, Mapping) or not isinstance(raw_response, Mapping):
        return None

    task_input = {
        key: value for key, value in raw_input.items() if isinstance(key, str)
    }
    response = {
        key: value for key, value in raw_response.items() if isinstance(key, str)
    }
    status = response.get("status")
    lifecycle = _claude_lifecycle(status)
    if lifecycle is None:
        return None

    session_id = payload.get("session_id")
    agent_id = response.get("agentId")
    return DelegatedWorkerEvent(
        source="claude_code_agent",
        lifecycle=lifecycle,
        task_input=task_input,
        parent_session_id=session_id if isinstance(session_id, str) else "",
        worker_id=agent_id if isinstance(agent_id, str) else "",
        result_text=_claude_agent_response_text(response),
    )


def claude_subagent_stop_event(
    payload: Mapping[str, object],
) -> DelegatedWorkerEvent | None:
    """Adapt Claude Code SubagentStop metadata to the neutral contract."""

    session_id = payload.get("session_id")
    agent_id = payload.get("agent_id")
    if not isinstance(session_id, str) or not isinstance(agent_id, str):
        return None
    message = payload.get("last_assistant_message")
    return DelegatedWorkerEvent(
        source="claude_code_subagent",
        lifecycle=WorkerLifecycle.COMPLETED,
        task_input={},
        parent_session_id=session_id,
        worker_id=agent_id,
        result_text=message if isinstance(message, str) else "",
    )


def _claude_lifecycle(value: object) -> WorkerLifecycle | None:
    if value == "async_launched":
        return WorkerLifecycle.BACKGROUND
    if value == "completed":
        return WorkerLifecycle.COMPLETED
    if value == "failed":
        return WorkerLifecycle.FAILED
    if value in {"cancelled", "canceled"}:
        return WorkerLifecycle.CANCELLED
    return None


def _claude_agent_response_text(response: Mapping[str, Any]) -> str:
    content = response.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, Mapping) or item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


__all__ = [
    "DelegatedWorkerEvent",
    "WorkerLifecycle",
    "claude_agent_posttool_event",
    "claude_subagent_stop_event",
]
