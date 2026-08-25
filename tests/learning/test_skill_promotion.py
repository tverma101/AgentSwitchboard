import json
from pathlib import Path

from free_claude_code.learning.engine import apply_learning_result
from free_claude_code.learning.promotion import (
    SkillPromotionCandidate,
    register_trusted_skill_promotion_check,
    unregister_trusted_skill_promotion_check,
)
from free_claude_code.learning.store import LearningStore

_SKILL_KEY = "fcc-auto-promotion-guard"
_BASE_INSTRUCTIONS = (
    "Run the focused tests, verify the diff, and check the final status before handoff."
)
_UPDATE_INSTRUCTIONS = (
    "Run the focused tests, verify the diff, and check the final status before handoff. "
    "Then record a compact validation receipt."
)


def _skill_result(*, action: str, instructions: str, **extra: object) -> dict[str, object]:
    return {
        "memory_actions": [],
        "skill": {
            "action": action,
            "name": "promotion-guard",
            "description": "Promote learned skill updates only after trusted validation.",
            "instructions": instructions,
            "scope": "global",
            "confidence": 0.98,
            "evidence_kind": "successful_workflow",
            **extra,
        },
    }


def _baseline(tmp_path: Path, monkeypatch) -> tuple[LearningStore, Path, str]:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    store = LearningStore(tmp_path / "learning.db")
    assert apply_learning_result(
        result=_skill_result(action="create", instructions=_BASE_INSTRUCTIONS),
        cwd=str(tmp_path),
        store=store,
    ) == {"memories": 0, "skills": 1}
    path = tmp_path / "claude" / "skills" / _SKILL_KEY / "SKILL.md"
    return store, path, path.read_text(encoding="utf-8")


def _receipts(tmp_path: Path) -> list[dict[str, object]]:
    receipt_path = tmp_path / "skill-promotion-receipts.jsonl"
    return [json.loads(line) for line in receipt_path.read_text().splitlines()]


def test_trusted_passing_gate_allows_replacement_and_records_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    store, path, original = _baseline(tmp_path, monkeypatch)

    def passes(candidate: SkillPromotionCandidate) -> bool:
        return (
            candidate.skill_key == _SKILL_KEY
            and candidate.current_content == original
            and "compact validation receipt" in candidate.candidate_content
        )

    register_trusted_skill_promotion_check(
        _SKILL_KEY,
        check_id="fixture-release-contract",
        version="1",
        evaluator=passes,
    )
    try:
        assert apply_learning_result(
            result=_skill_result(action="update", instructions=_UPDATE_INSTRUCTIONS),
            cwd=str(tmp_path),
            store=store,
        ) == {"memories": 0, "skills": 1}
    finally:
        assert unregister_trusted_skill_promotion_check(_SKILL_KEY)

    assert path.read_text(encoding="utf-8") != original
    assert len(store.skill_revisions(_SKILL_KEY)) == 2
    receipt = _receipts(tmp_path)[-1]
    assert receipt["decision"] == "pass"
    assert receipt["check_id"] == "fixture-release-contract"
    assert receipt["check_version"] == "1"
    assert len(str(receipt["current_digest"])) == 64
    assert len(str(receipt["candidate_digest"])) == 64
    raw_receipt = json.dumps(receipt)
    assert "compact validation receipt" not in raw_receipt
    assert original not in raw_receipt


def test_trusted_failing_gate_rejects_candidate_selected_bypass(
    tmp_path: Path, monkeypatch
) -> None:
    store, path, original = _baseline(tmp_path, monkeypatch)
    marker = tmp_path / "candidate-owned-marker"
    register_trusted_skill_promotion_check(
        _SKILL_KEY,
        check_id="trusted-fail",
        version="2",
        evaluator=lambda candidate: False,
    )
    try:
        assert apply_learning_result(
            result=_skill_result(
                action="update",
                instructions=_UPDATE_INSTRUCTIONS,
                check_id="candidate-owned-pass",
                promotion_command=f"touch {marker}",
            ),
            cwd=str(tmp_path),
            store=store,
        ) == {"memories": 0, "skills": 0}
    finally:
        assert unregister_trusted_skill_promotion_check(_SKILL_KEY)

    assert path.read_text(encoding="utf-8") == original
    assert len(store.skill_revisions(_SKILL_KEY)) == 1
    record = store.skill_record(_SKILL_KEY)
    assert record is not None
    assert record["revision"] == 1
    receipt = _receipts(tmp_path)[-1]
    assert receipt["decision"] == "fail"
    assert receipt["check_id"] == "trusted-fail"
    raw_receipt = json.dumps(receipt)
    assert "candidate-owned-pass" not in raw_receipt
    assert "promotion_command" not in raw_receipt
    assert not marker.exists()


def test_trusted_gate_error_fails_closed_without_revision_change(
    tmp_path: Path, monkeypatch
) -> None:
    store, path, original = _baseline(tmp_path, monkeypatch)

    def errors(candidate: SkillPromotionCandidate) -> bool:
        raise RuntimeError("fixture adapter failed")

    register_trusted_skill_promotion_check(
        _SKILL_KEY,
        check_id="fixture-error",
        version="1",
        evaluator=errors,
    )
    try:
        assert apply_learning_result(
            result=_skill_result(action="update", instructions=_UPDATE_INSTRUCTIONS),
            cwd=str(tmp_path),
            store=store,
        ) == {"memories": 0, "skills": 0}
    finally:
        assert unregister_trusted_skill_promotion_check(_SKILL_KEY)

    assert path.read_text(encoding="utf-8") == original
    assert len(store.skill_revisions(_SKILL_KEY)) == 1
    receipt = _receipts(tmp_path)[-1]
    assert receipt["decision"] == "error"
    assert receipt["check_id"] == "fixture-error"


def test_unregistered_skill_keeps_structural_policy_and_records_no_gate(
    tmp_path: Path, monkeypatch
) -> None:
    store, path, original = _baseline(tmp_path, monkeypatch)
    assert apply_learning_result(
        result=_skill_result(action="update", instructions=_UPDATE_INSTRUCTIONS),
        cwd=str(tmp_path),
        store=store,
    ) == {"memories": 0, "skills": 1}

    assert path.read_text(encoding="utf-8") != original
    assert len(store.skill_revisions(_SKILL_KEY)) == 2
    receipt = _receipts(tmp_path)[-1]
    assert receipt["decision"] == "no_gate"
    assert receipt["check_id"] == ""
    assert receipt["check_version"] == ""
