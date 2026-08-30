"""Legacy reviewer-scar persistence contracts kept off Claude's runtime path."""

from pathlib import Path

import pytest

from free_claude_code.learning.auto_reviewer import persist_from_message
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
