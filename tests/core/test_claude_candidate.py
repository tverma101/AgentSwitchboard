"""Deterministic Claude candidate certification and rollback contracts."""

import json

import pytest

from free_claude_code.core.claude_candidate import (
    ClaudeCandidateError,
    ClaudeCandidateProcess,
    assess_claude_candidate,
    initial_claude_release_state,
    promote_claude_candidate,
    record_claude_candidate,
    rollback_claude_candidate,
    stage_claude_candidate,
)

KNOWN_GOOD = {
    "version": "2.1.228",
    "route": "fcc://known-good",
    "contract": {
        "request": ["messages", "tools"],
        "response": {"stream": "sse", "tool_use": "stable"},
    },
}


def _candidate(**overrides: object) -> dict[str, object]:
    candidate = {
        "version": "2.1.229",
        "route": "fcc://candidate",
        "contract": {
            "request": ["messages", "tools"],
            "response": {"stream": "sse", "tool_use": "stable"},
        },
        "release_notes": "safe additive metadata",
    }
    candidate.update(overrides)
    return candidate


def _process(version: str = "2.1.229") -> ClaudeCandidateProcess:
    return ClaudeCandidateProcess(exit_code=0, version_output=f"Claude Code {version}")


def test_candidate_certification_is_pure_and_preserves_explicit_routing() -> None:
    state = initial_claude_release_state(
        last_known_good_version="2.1.228", last_known_good_route="fcc://known-good"
    )
    staged = stage_claude_candidate(state, version="2.1.229", route="fcc://candidate")
    assessment = assess_claude_candidate(
        staged,
        known_good_metadata=KNOWN_GOOD,
        candidate_metadata=_candidate(),
        process=_process(),
    )

    assert assessment.state == "certified"
    assert assessment.active_version == "2.1.228"
    assert assessment.active_route == "fcc://known-good"
    assert staged.last_known_good_version == "2.1.228"
    assert staged.last_known_good_route == "fcc://known-good"
    assert staged.active_route == "fcc://known-good"
    assert staged.candidate_state == "candidate"


def test_safe_additive_fields_are_accepted() -> None:
    state = initial_claude_release_state(
        last_known_good_version="2.1.228", last_known_good_route="fcc://known-good"
    )
    assessment = assess_claude_candidate(
        state,
        known_good_metadata=KNOWN_GOOD,
        candidate_metadata={
            **_candidate(),
            "new_top_level_field": {"observed_at": "synthetic"},
            "contract": {
                "request": ["messages", "tools"],
                "response": {"stream": "sse", "tool_use": "stable"},
                "optional_capability": "new",
            },
        },
        process=_process(),
    )

    assert assessment.certified
    assert assessment.evidence == ()


def test_semantic_contract_change_is_quarantined_with_sanitized_evidence() -> None:
    state = initial_claude_release_state(
        last_known_good_version="2.1.228", last_known_good_route="fcc://known-good"
    )
    changed = _candidate(
        contract={
            "request": ["messages", "tools"],
            "response": {"stream": "json", "tool_use": "stable"},
        }
    )
    assessment = assess_claude_candidate(
        state,
        known_good_metadata=KNOWN_GOOD,
        candidate_metadata=changed,
        process=ClaudeCandidateProcess(
            exit_code=1,
            version_output="Claude Code 2.1.229",
            stderr="contract mismatch token=sk-candidate-secret",
        ),
    )

    assert assessment.state == "quarantined"
    codes = {item.code for item in assessment.evidence}
    assert codes == {"candidate_process_failed", "semantic_contract_changed"}
    serialized = json.dumps(assessment.as_receipt())
    assert "sk-candidate-secret" not in serialized
    assert "<redacted>" in serialized
    assert assessment.active_route == "fcc://known-good"


def test_explicit_promotion_then_rollback_restores_last_known_good() -> None:
    state = initial_claude_release_state(
        last_known_good_version="2.1.228", last_known_good_route="fcc://known-good"
    )
    staged = stage_claude_candidate(state, version="2.1.229", route="fcc://candidate")
    assessment = assess_claude_candidate(
        staged,
        known_good_metadata=KNOWN_GOOD,
        candidate_metadata=_candidate(),
        process=_process(),
    )
    certified = record_claude_candidate(staged, assessment)
    promoted = promote_claude_candidate(certified)
    rolled_back = rollback_claude_candidate(promoted)

    assert promoted.active_version == "2.1.229"
    assert promoted.active_route == "fcc://candidate"
    assert promoted.last_known_good_version == "2.1.228"
    assert rolled_back.candidate_state == "rolled_back"
    assert rolled_back.active_version == "2.1.228"
    assert rolled_back.active_route == "fcc://known-good"


def test_quarantined_candidate_cannot_be_promoted() -> None:
    state = initial_claude_release_state(
        last_known_good_version="2.1.228", last_known_good_route="fcc://known-good"
    )
    assessment = assess_claude_candidate(
        state,
        known_good_metadata=KNOWN_GOOD,
        candidate_metadata=_candidate(
            contract={"request": ["messages"], "response": {"stream": "sse"}}
        ),
        process=_process(),
    )

    with pytest.raises(ClaudeCandidateError, match="certified"):
        promote_claude_candidate(record_claude_candidate(state, assessment))
