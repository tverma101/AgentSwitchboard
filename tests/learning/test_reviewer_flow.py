"""Contracts for legacy reviewer records kept outside Claude orchestration."""

from pathlib import Path

import pytest

from free_claude_code.learning.reviewer_flow import (
    MAX_REVIEW_CONTEXT_BYTES,
    admit_exit_candidate,
    build_reviewer_plan,
    fingerprint_task,
    parse_exit_ticket,
    persist_exit_candidate,
)
from free_claude_code.learning.reviewer_scars import (
    ExitStatus,
    PreventionClass,
    ReviewerPack,
    ScarCandidate,
    ScarKind,
    ScarRegistry,
    ScarState,
    SubagentExitTicket,
    VerificationLevel,
    admit_scar_candidate,
)


def _candidate(
    *,
    pack: ReviewerPack = ReviewerPack.EDGE_CASES,
    evidence: tuple[str, ...] = ("pr:148",),
    prevention: PreventionClass = PreventionClass.HOURS_DEBUGGING,
) -> ScarCandidate:
    return ScarCandidate(
        pack=pack,
        kind=ScarKind.CAVE,
        scope="macos/browser",
        condition="backend:absent",
        rule="check=runtime.registration;avoid=reinstall",
        state=ScarState.VERIFIED,
        prevention=prevention,
        evidence=evidence,
    )


def _ticket(*, learn: bool = True) -> SubagentExitTicket:
    return SubagentExitTicket(
        status=ExitStatus.DONE,
        implemented=True,
        verification=VerificationLevel.TESTS,
        cave="backend:absent",
        learn_candidate=learn,
        evidence=("pr:148",),
    )


def test_task_fingerprint_canonicalizes_common_delegation_signals() -> None:
    fingerprint = fingerprint_task(
        {
            "prompt": "Fix the Chrome browser backend on macOS",
            "description": "Check the runtime registration before reinstalling",
            "risk": "false-completion",
        }
    )

    assert fingerprint.scopes == ("browser", "macos")
    assert fingerprint.operations == ("fix",)
    assert fingerprint.risks == ("false-completion",)


def test_plan_injects_only_matching_scars_under_hard_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    registry = ScarRegistry("coding")
    registry.upsert(admit_scar_candidate(_candidate()))
    registry.upsert(admit_scar_candidate(_candidate(pack=ReviewerPack.EFFICIENCY)))

    plan = build_reviewer_plan(
        "Fix the Chrome browser backend on macOS",
        registry=registry,
    )

    assert plan.packs == (
        ReviewerPack.EDGE_CASES,
        ReviewerPack.IMPLEMENTATION_TRUTH,
    )
    assert len(plan.selection.lines) == 1
    assert "pack=edge-cases" in plan.context()
    assert "pack=efficiency" not in plan.context()
    assert len(plan.context().encode("utf-8")) <= MAX_REVIEW_CONTEXT_BYTES


def test_exit_ticket_parser_discards_prose_and_rejects_ambiguous_output() -> None:
    value = _ticket().compact()
    accepted = parse_exit_ticket(f"Some prose\n{value}\n")

    assert accepted.reason == "accepted"
    assert accepted.ticket == _ticket()
    assert parse_exit_ticket("no ticket").reason == "missing_x1"
    assert parse_exit_ticket(f"{value}\n{value}").reason == "multiple_x1_lines"
    assert parse_exit_ticket(value.replace("verify=tests", "verify=bogus")).reason == (
        "malformed_x1"
    )


def test_ticket_candidate_still_requires_the_counterfactual_gate() -> None:
    result = parse_exit_ticket(_ticket().compact())

    assert not admit_exit_candidate(
        result,
        _candidate(prevention=PreventionClass.NONE),
    ).promote
    decision = admit_exit_candidate(result, _candidate())
    assert decision.promote is True
    assert decision.record is not None

    assert (
        admit_exit_candidate(
            parse_exit_ticket(_ticket(learn=False).compact()), _candidate()
        ).reason
        == "exit_ticket_did_not_nominate"
    )


def test_persist_requires_explicitly_supplied_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    registry = ScarRegistry("coding")
    result = parse_exit_ticket(_ticket().compact())

    decision = persist_exit_candidate(result, _candidate(), registry=registry)

    assert decision.promote is True
    assert len(registry.load()) == 1
