"""Contracts for bounded reviewer packs, scars, and exit tickets."""

import json
from pathlib import Path

import pytest

import free_claude_code.learning.reviewer_scars as scars


def _candidate(**updates: object) -> scars.ScarCandidate:
    values: dict[str, object] = {
        "pack": scars.ReviewerPack.IMPLEMENTATION_TRUTH,
        "kind": scars.ScarKind.TRUTH,
        "scope": "terminal",
        "condition": "merged without current-main validation",
        "rule": "rebase and rerun the protected local gate",
        "state": scars.ScarState.VERIFIED,
        "prevention": scars.PreventionClass.FALSE_COMPLETION,
        "evidence": ("local-ci",),
    }
    values.update(updates)
    return scars.ScarCandidate(**values)


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> scars.ScarRegistry:
    monkeypatch.setattr(scars, "profile_home", lambda profile=None: tmp_path)
    return scars.ScarRegistry("default")


def test_reviewer_pack_selection_is_ordered_and_signal_driven() -> None:
    fingerprint = scars.TaskFingerprint(
        scopes=("macOS",),
        operations=("benchmark", "integration", "cleanup"),
        risks=("duplicate-runtime",),
    )

    assert scars.select_reviewer_packs(fingerprint) == (
        scars.ReviewerPack.EFFICIENCY,
        scars.ReviewerPack.EDGE_CASES,
        scars.ReviewerPack.IMPLEMENTATION_TRUTH,
        scars.ReviewerPack.REDUNDANCY,
    )


def test_profile_overrides_only_change_explicit_pack_choices() -> None:
    assert scars.resolve_enabled_packs(
        {scars.ReviewerPack.EFFICIENCY, scars.ReviewerPack.EDGE_CASES},
        {scars.ReviewerPack.EFFICIENCY: False, scars.ReviewerPack.REDUNDANCY: True},
    ) == (scars.ReviewerPack.EDGE_CASES, scars.ReviewerPack.REDUNDANCY)


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"prevention": scars.PreventionClass.NONE}, "no_concrete_prevented_pain"),
        ({"state": scars.ScarState.OBSERVED}, "evidence_state_not_promotable"),
        ({"evidence": ()}, "missing_evidence"),
    ],
)
def test_admission_gate_drops_unsupported_candidates(
    updates: dict[str, object], reason: str
) -> None:
    decision = scars.admit_scar_candidate(_candidate(**updates))

    assert decision.promote is False
    assert decision.reason == reason
    assert decision.record is None


def test_admission_deduplicates_evidence_and_creates_stable_id() -> None:
    decision = scars.admit_scar_candidate(
        _candidate(evidence=("z-receipt", "a-receipt", "z-receipt"))
    )

    assert decision.promote is True
    assert decision.record is not None
    assert decision.record.evidence == ("a-receipt", "z-receipt")
    assert len(decision.record.scar_id) == 20


def test_exit_ticket_round_trips_and_rejects_ambiguous_fields() -> None:
    ticket = scars.SubagentExitTicket(
        status=scars.ExitStatus.PARTIAL,
        implemented=True,
        verification=scars.VerificationLevel.TESTS,
        blocker="live device permission",
        cave="provider spend not attempted",
        learn_candidate=True,
        evidence=("pytest", "device-check"),
        next_action="enable Accessibility",
    )

    assert scars.SubagentExitTicket.parse(ticket.compact()) == ticket
    with pytest.raises(scars.ReviewerScarError, match="unambiguous"):
        scars.SubagentExitTicket(
            status=scars.ExitStatus.FAIL,
            implemented=False,
            verification=scars.VerificationLevel.NONE,
            blocker="bad|field",
        ).compact()
    with pytest.raises(scars.ReviewerScarError, match="commas"):
        scars.SubagentExitTicket(
            status=scars.ExitStatus.FAIL,
            implemented=False,
            verification=scars.VerificationLevel.NONE,
            evidence=("one,two",),
        ).compact()


def test_selection_filters_states_and_honors_byte_and_record_budgets() -> None:
    promoted = scars.admit_scar_candidate(_candidate()).record
    stale = scars.ScarRecord(
        scar_id="stale",
        pack=scars.ReviewerPack.IMPLEMENTATION_TRUTH,
        kind=scars.ScarKind.TRUTH,
        scope="old",
        condition="old",
        rule="old",
        state=scars.ScarState.STALE,
        prevention=scars.PreventionClass.FALSE_COMPLETION,
        evidence=("old-receipt",),
    )
    assert promoted is not None

    selection = scars.select_scars_for_context(
        [stale, promoted],
        [scars.ReviewerPack.IMPLEMENTATION_TRUTH],
        max_bytes=10_000,
        max_tokens=10_000,
        max_records=1,
    )

    assert selection.lines == (promoted.compact(),)
    assert selection.bytes_used == len((selection.lines[0] + "\n").encode())
    assert selection.estimated_tokens == (selection.bytes_used + 3) // 4


def test_registry_persists_merges_and_tracks_state_history(
    registry: scars.ScarRegistry,
) -> None:
    first = scars.admit_scar_candidate(_candidate(evidence=("first",)))
    second = scars.admit_scar_candidate(
        _candidate(state=scars.ScarState.MITIGATED, evidence=("second",))
    )
    assert first.record is not None
    assert second.record is not None

    saved = registry.upsert(first)
    merged = registry.upsert(second)

    assert saved == first.record
    assert merged.state is scars.ScarState.MITIGATED
    assert merged.history == (scars.ScarState.VERIFIED,)
    assert merged.evidence == ("first", "second")
    assert registry.load() == (merged,)
    assert registry.path.stat().st_mode & 0o777 == 0o600

    updated = registry.update_state(merged.scar_id, scars.ScarState.STALE)
    assert updated.state is scars.ScarState.STALE
    assert updated.history == (
        scars.ScarState.VERIFIED,
        scars.ScarState.MITIGATED,
    )


def test_registry_rejects_tampered_records_and_symlink_paths(
    registry: scars.ScarRegistry,
) -> None:
    decision = scars.admit_scar_candidate(_candidate())
    assert decision.record is not None
    registry.upsert(decision)
    payload = json.loads(registry.path.read_text(encoding="utf-8"))
    payload["records"][0]["scar_id"] = "tampered"
    registry.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(scars.ReviewerScarError, match="does not match"):
        registry.load()

    registry.path.unlink()
    target = registry.path.with_name("target.json")
    target.write_text("{}", encoding="utf-8")
    registry.path.symlink_to(target)
    with pytest.raises(scars.ReviewerScarError, match="must not be a symlink"):
        registry.load()
    with pytest.raises(scars.ReviewerScarError, match="must not be a symlink"):
        registry.upsert(decision)
