"""Deterministic coverage for bounded reviewer/scar learning."""

import os
from pathlib import Path

import pytest

from free_claude_code.learning.reviewer_scars import (
    ExitStatus,
    PreventionClass,
    ReviewerPack,
    ReviewerScarError,
    ScarCandidate,
    ScarKind,
    ScarRegistry,
    ScarState,
    SubagentExitTicket,
    TaskFingerprint,
    VerificationLevel,
    admit_scar_candidate,
    resolve_enabled_packs,
    select_reviewer_packs,
    select_scars_for_context,
)


def _candidate(
    *,
    pack: ReviewerPack = ReviewerPack.EDGE_CASES,
    kind: ScarKind = ScarKind.CAVE,
    state: ScarState = ScarState.REPRODUCED,
    prevention: PreventionClass = PreventionClass.HOURS_DEBUGGING,
    evidence: tuple[str, ...] = ("gh:#123",),
) -> ScarCandidate:
    return ScarCandidate(
        pack=pack,
        kind=kind,
        scope="macos/browser",
        condition="backend:absent",
        rule="check=runtime.registration;avoid=reinstall",
        state=state,
        prevention=prevention,
        evidence=evidence,
    )


def test_pack_selection_is_small_for_three_distinct_task_classes() -> None:
    assert select_reviewer_packs(
        TaskFingerprint(operations=("cleanup",), risks=("duplicate-code",))
    ) == (
        ReviewerPack.IMPLEMENTATION_TRUTH,
        ReviewerPack.REDUNDANCY,
    )
    assert select_reviewer_packs(TaskFingerprint(operations=("performance",))) == (
        ReviewerPack.EFFICIENCY,
        ReviewerPack.EDGE_CASES,
    )
    assert select_reviewer_packs(
        TaskFingerprint(scopes=("macos",), operations=("integration",))
    ) == (
        ReviewerPack.EDGE_CASES,
        ReviewerPack.IMPLEMENTATION_TRUTH,
    )


def test_counterfactual_gate_defaults_to_drop() -> None:
    decision = admit_scar_candidate(_candidate(prevention=PreventionClass.NONE))

    assert decision.promote is False
    assert decision.reason == "no_concrete_prevented_pain"
    assert decision.record is None


def test_observation_without_reproduction_does_not_promote() -> None:
    decision = admit_scar_candidate(_candidate(state=ScarState.OBSERVED))

    assert decision.promote is False
    assert decision.reason == "evidence_state_not_promotable"


def test_reproduced_high_value_candidate_promotes_to_typed_compact_scar() -> None:
    decision = admit_scar_candidate(_candidate())

    assert decision.promote is True
    assert decision.record is not None
    line = decision.record.compact()
    assert line.startswith("C1|pack=edge-cases|scope=macos/browser|")
    assert "pain=hours_debugging" in line
    assert "ev=gh:#123" in line


def test_negative_rule_remains_first_class() -> None:
    decision = admit_scar_candidate(
        ScarCandidate(
            pack=ReviewerPack.REDUNDANCY,
            kind=ScarKind.NEGATIVE,
            scope="browser",
            condition="existing-runtime:yes",
            rule="ban=new-browser-engine;use=codex-runtime",
            state=ScarState.VERIFIED,
            prevention=PreventionClass.DANGEROUS_DUPLICATION,
            evidence=("pr:148",),
        )
    )

    assert decision.record is not None
    assert decision.record.compact().startswith("N1|")


def test_secret_like_candidate_is_rejected() -> None:
    with pytest.raises(ReviewerScarError, match="secret"):
        admit_scar_candidate(
            ScarCandidate(
                pack=ReviewerPack.EDGE_CASES,
                kind=ScarKind.CAVE,
                scope="provider",
                condition="api_key=super-secret-value",
                rule="avoid=leak",
                state=ScarState.REPRODUCED,
                prevention=PreventionClass.PROVIDER_SPEND,
                evidence=("test:secret-redaction",),
            )
        )


def test_registry_is_profile_isolated_dedupes_and_retains_state_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    first = ScarRegistry("coding")
    other = ScarRegistry("school")

    decision = admit_scar_candidate(_candidate(evidence=("gh:#123",)))
    assert decision.record is not None
    saved = first.upsert(decision)
    assert len(first.load()) == 1
    assert other.load() == ()

    duplicate = admit_scar_candidate(_candidate(evidence=("pr:148",)))
    merged = first.upsert(duplicate)
    assert merged.scar_id == saved.scar_id
    assert merged.evidence == ("gh:#123", "pr:148")
    assert len(first.load()) == 1

    mitigated = first.update_state(saved.scar_id, ScarState.MITIGATED)
    assert mitigated.state is ScarState.MITIGATED
    assert mitigated.history == (ScarState.REPRODUCED,)
    assert first.path.stat().st_mode & 0o077 == 0


def test_context_selection_respects_pack_and_token_byte_budgets() -> None:
    edge = admit_scar_candidate(_candidate()).record
    efficiency = admit_scar_candidate(
        ScarCandidate(
            pack=ReviewerPack.EFFICIENCY,
            kind=ScarKind.EFFICIENCY,
            scope="ci",
            condition="runner:single",
            rule="batch=checks;avoid=duplicate-gates",
            state=ScarState.VERIFIED,
            prevention=PreventionClass.HOURS_DEBUGGING,
            evidence=("pr:138",),
        )
    ).record
    assert edge is not None and efficiency is not None

    selection = select_scars_for_context(
        [edge, efficiency],
        [ReviewerPack.EDGE_CASES],
        max_bytes=4_096,
        max_tokens=1_024,
    )

    assert len(selection.lines) == 1
    assert "pack=edge-cases" in selection.lines[0]
    assert "pack=efficiency" not in selection.lines[0]
    assert selection.bytes_used <= 4_096
    assert selection.estimated_tokens <= 1_024


def test_shared_packs_allow_explicit_profile_overrides() -> None:
    shared = frozenset({ReviewerPack.EDGE_CASES, ReviewerPack.EFFICIENCY})

    enabled = resolve_enabled_packs(
        shared,
        {
            ReviewerPack.EDGE_CASES: False,
            ReviewerPack.IMPLEMENTATION_TRUTH: True,
        },
    )

    assert enabled == (
        ReviewerPack.EFFICIENCY,
        ReviewerPack.IMPLEMENTATION_TRUTH,
    )


def test_exit_ticket_round_trips_in_tens_of_tokens() -> None:
    ticket = SubagentExitTicket(
        status=ExitStatus.PARTIAL,
        implemented=True,
        verification=VerificationLevel.TESTS,
        blocker="mac-live",
        cave="browser.backend",
        learn_candidate=True,
        evidence=("pr:148", "gh:#29389"),
        next_action="run=device-canary",
    )

    compact = ticket.compact()
    restored = SubagentExitTicket.parse(compact)

    assert compact.startswith("X1|st=PARTIAL|impl=1|verify=tests|")
    assert len(compact.encode("utf-8")) < 256
    assert restored == ticket


def test_registry_does_not_depend_on_process_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    monkeypatch.chdir(tmp_path)
    registry = ScarRegistry("coding")

    registry.upsert(admit_scar_candidate(_candidate()))

    assert registry.path.is_file()
    assert registry.path.parent == tmp_path / "learning" / "profiles" / "coding"
    assert os.fspath(registry.path).endswith("reviewer-scars.json")
