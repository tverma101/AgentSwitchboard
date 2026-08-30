"""Contracts for automatic reviewer-scar learning on Claude Agent hooks."""

import io
import json
import sys
from pathlib import Path

import pytest

from free_claude_code.learning.auto_reviewer import (
    AUTO_CONTEXT_START,
    augment_agent_input,
    persist_from_message,
)
from free_claude_code.learning.hooks import run_hook
from free_claude_code.learning.reviewer_flow import build_reviewer_plan
from free_claude_code.learning.reviewer_scars import (
    ExitStatus,
    ScarRegistry,
    SubagentExitTicket,
    VerificationLevel,
)


def _ticket(*, learn: bool = True) -> SubagentExitTicket:
    return SubagentExitTicket(
        status=ExitStatus.DONE,
        implemented=True,
        verification=VerificationLevel.TESTS,
        cave="backend_absent",
        learn_candidate=learn,
        evidence=("pr:148",),
        next_action="check_registration_first",
    )


def _a1(*, pack: str = "edge-cases", evidence: str = "pr:148") -> str:
    return (
        "A1|"
        f"pack={pack}|kind=C1|scope=macos/browser|when=backend_absent|"
        "rule=check_registration_first|pain=hours_debugging|"
        f"ev={evidence}"
    )


def _message(*, learn: bool = True, pack: str = "edge-cases") -> str:
    return f"{_ticket(learn=learn).compact()}\n{_a1(pack=pack)}"


def test_agent_input_gets_task_matched_reviewer_and_auto_learning_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))

    updated = augment_agent_input(
        {
            "prompt": "Fix the Chrome browser backend on macOS",
            "description": "Check registration before reinstalling anything",
            "subagent_type": "Explore",
        },
        profile="coding",
    )

    assert updated is not None
    prompt = updated["prompt"]
    assert isinstance(prompt, str)
    assert AUTO_CONTEXT_START in prompt
    assert "pack must be one of [edge-cases,implementation-truth]" in prompt
    assert "A1|pack=<pack>" in prompt
    assert prompt.startswith("Fix the Chrome browser backend on macOS")


def test_auto_persistence_requires_matching_x1_a1_and_selected_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    registry = ScarRegistry("coding")
    plan = build_reviewer_plan(
        "Fix the Chrome browser backend on macOS",
        profile="coding",
        registry=registry,
    )

    promoted = persist_from_message(_message(), plan=plan, registry=registry)

    assert promoted.outcome.promoted is True
    assert promoted.outcome.scar_id is not None
    rows = registry.load()
    assert len(rows) == 1
    assert rows[0].condition == "backend_absent"
    assert rows[0].rule == "check_registration_first"
    assert rows[0].prevention.value == "hours_debugging"

    wrong_pack = persist_from_message(
        _message(pack="efficiency"), plan=plan, registry=registry
    )
    assert wrong_pack.outcome.promoted is False
    assert wrong_pack.outcome.reason == "a1_pack_not_selected"
    assert len(registry.load()) == 1


def test_auto_persistence_drops_legacy_or_nonlearning_tickets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    registry = ScarRegistry("coding")
    plan = build_reviewer_plan(
        "Fix the Chrome browser backend on macOS",
        profile="coding",
        registry=registry,
    )

    legacy = persist_from_message(_ticket().compact(), plan=plan, registry=registry)
    assert legacy.outcome.promoted is False
    assert legacy.outcome.reason == "missing_a1"

    nolearn = persist_from_message(_message(learn=False), plan=plan, registry=registry)
    assert nolearn.outcome.promoted is False
    assert nolearn.outcome.reason == "x1_learn_false"
    assert registry.load() == ()


def test_foreground_agent_hooks_auto_persist_and_return_parent_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FCC_LEARNING_ENABLED", "1")
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    tool_input = {
        "prompt": "Fix the Chrome browser backend on macOS",
        "description": "Check registration before reinstalling anything",
        "subagent_type": "Explore",
    }

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "session-1",
                    "tool_name": "Agent",
                    "tool_input": tool_input,
                }
            )
        ),
    )
    run_hook("agent-pre", profile="coding")
    pre = json.loads(capsys.readouterr().out)
    updated_input = pre["hookSpecificOutput"]["updatedInput"]
    assert AUTO_CONTEXT_START in updated_input["prompt"]
    assert "permissionDecision" not in pre["hookSpecificOutput"]

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "session-1",
                    "tool_name": "Agent",
                    "tool_input": updated_input,
                    "tool_response": {
                        "status": "completed",
                        "agentId": "agent-1",
                        "content": [{"type": "text", "text": _message()}],
                    },
                }
            )
        ),
    )
    run_hook("agent-post", profile="coding")
    post = json.loads(capsys.readouterr().out)
    context = post["hookSpecificOutput"]["additionalContext"]
    assert "status=DONE" in context
    assert "X1|" not in context
    assert "auto-learn: promoted" in context
    assert len(ScarRegistry("coding").load()) == 1


def test_background_agent_plan_is_metadata_only_and_persists_on_subagent_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    learning_home = tmp_path / "learning"
    monkeypatch.setenv("FCC_LEARNING_ENABLED", "1")
    monkeypatch.setenv("FCC_LEARNING_HOME", str(learning_home))
    tool_input = {
        "prompt": "Fix the Chrome browser backend on macOS",
        "description": "Check registration before reinstalling anything",
        "subagent_type": "Explore",
    }

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "session-bg",
                    "tool_name": "Agent",
                    "tool_input": tool_input,
                    "tool_response": {
                        "status": "async_launched",
                        "agentId": "agent-bg",
                    },
                }
            )
        ),
    )
    run_hook("agent-post", profile="coding")
    assert json.loads(capsys.readouterr().out) == {}

    pending = learning_home / "profiles" / "coding" / "reviewer-pending.json"
    pending_text = pending.read_text(encoding="utf-8")
    assert "Fix the Chrome" not in pending_text
    assert "session-bg" not in pending_text
    assert "agent-bg" not in pending_text
    assert "edge-cases" in pending_text

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "session-bg",
                    "agent_id": "agent-bg",
                    "agent_type": "Explore",
                    "last_assistant_message": _message(),
                }
            )
        ),
    )
    run_hook("subagent-stop", profile="coding")
    assert json.loads(capsys.readouterr().out) == {}
    assert len(ScarRegistry("coding").load()) == 1
    assert "edge-cases" not in pending.read_text(encoding="utf-8")
