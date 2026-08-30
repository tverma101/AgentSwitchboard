from pathlib import Path

import pytest

from free_claude_code.learning.delegated_worker import (
    DelegatedWorkerEvent,
    WorkerLifecycle,
    claude_agent_posttool_event,
    claude_subagent_stop_event,
)
from free_claude_code.learning.reviewer_scars import (
    ExitStatus,
    SubagentExitTicket,
    VerificationLevel,
)
from free_claude_code.learning.worker_reviewer import (
    process_background_worker_stop,
    process_worker_event,
)


def _nolearn_ticket() -> str:
    return SubagentExitTicket(
        status=ExitStatus.DONE,
        implemented=True,
        verification=VerificationLevel.TESTS,
        cave="backend_absent",
        learn_candidate=False,
        evidence=("test:worker",),
        next_action="check_registration_first",
    ).compact()


def test_claude_agent_payload_is_only_an_adapter_shape() -> None:
    event = claude_agent_posttool_event(
        {
            "session_id": "session-1",
            "tool_name": "Agent",
            "tool_input": {"prompt": "Inspect provider routing"},
            "tool_response": {
                "status": "completed",
                "agentId": "agent-1",
                "content": [{"type": "text", "text": "done"}],
            },
        }
    )

    assert event == DelegatedWorkerEvent(
        source="claude_code_agent",
        lifecycle=WorkerLifecycle.COMPLETED,
        task_input={"prompt": "Inspect provider routing"},
        parent_session_id="session-1",
        worker_id="agent-1",
        result_text="done",
    )


def test_claude_subagent_stop_normalizes_without_exposing_payload_shape() -> None:
    event = claude_subagent_stop_event(
        {
            "session_id": "session-bg",
            "agent_id": "agent-bg",
            "last_assistant_message": "finished",
        }
    )

    assert event is not None
    assert event.source == "claude_code_subagent"
    assert event.lifecycle is WorkerLifecycle.COMPLETED
    assert event.parent_session_id == "session-bg"
    assert event.worker_id == "agent-bg"
    assert event.result_text == "finished"


def test_reviewer_core_accepts_non_claude_worker_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    event = DelegatedWorkerEvent(
        source="configured_provider_worker",
        lifecycle=WorkerLifecycle.COMPLETED,
        task_input={"prompt": "Fix the Chrome browser backend on macOS"},
        parent_session_id="parent-1",
        worker_id="worker-1",
        result_text=_nolearn_ticket(),
    )

    result = process_worker_event(event, profile="coding")

    assert result is not None
    assert result.outcome.promoted is False
    assert result.outcome.reason == "x1_learn_false"


def test_background_handoff_is_worker_source_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    launched = DelegatedWorkerEvent(
        source="codex_bounded_worker",
        lifecycle=WorkerLifecycle.BACKGROUND,
        task_input={"prompt": "Fix the Chrome browser backend on macOS"},
        parent_session_id="parent-bg",
        worker_id="worker-bg",
    )

    assert process_worker_event(launched, profile="coding") is None

    completed = DelegatedWorkerEvent(
        source="codex_bounded_worker",
        lifecycle=WorkerLifecycle.COMPLETED,
        task_input={},
        parent_session_id="parent-bg",
        worker_id="worker-bg",
        result_text=_nolearn_ticket(),
    )
    result = process_background_worker_stop(completed, profile="coding")

    assert result is not None
    assert result.outcome.promoted is False
    assert result.outcome.reason == "x1_learn_false"
