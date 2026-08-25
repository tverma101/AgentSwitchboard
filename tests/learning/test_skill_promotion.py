"""Behavior contracts for trusted generated-skill promotion checks."""

import json
import sys
from pathlib import Path
from typing import Any

from free_claude_code.learning import promotion
from free_claude_code.learning.engine import apply_learning_result
from free_claude_code.learning.store import LearningStore

_SKILL_KEY = "fcc-auto-review-work"


def _skill(instructions: str, *, action: str, **extra: Any) -> dict[str, Any]:
    return {
        "memory_actions": [],
        "skill": {
            "action": action,
            "name": "review-work",
            "description": "Review the work before handing it off.",
            "instructions": instructions,
            "scope": "global",
            "confidence": 0.98,
            "evidence_kind": "successful_workflow",
            **extra,
        },
    }


def _seed_skill(tmp_path: Path, store: LearningStore) -> tuple[Path, str]:
    first = _skill(
        "Run the focused tests, verify the diff, and check the final status before handoff.",
        action="create",
    )
    assert apply_learning_result(result=first, cwd=str(tmp_path), store=store) == {
        "memories": 0,
        "skills": 1,
    }
    path = tmp_path / "claude" / "skills" / _SKILL_KEY / "SKILL.md"
    return path, path.read_text(encoding="utf-8")


def _write_fixture_check(tmp_path: Path) -> Path:
    script = tmp_path / "promotion_check.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "candidate = Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "raise SystemExit(0 if sys.argv[2] in candidate else 9)\n",
        encoding="utf-8",
    )
    return script


def _write_sidecar(
    store: LearningStore,
    *,
    argv: list[str],
    check_id: str = "review-work-fixture",
) -> None:
    sidecar = store.profile_home / "skill-promotion-checks.json"
    sidecar.write_text(
        json.dumps(
            {
                "version": 1,
                "skills": {
                    _SKILL_KEY: {
                        "check_id": check_id,
                        "check_version": "1",
                        "argv": argv,
                        "timeout_seconds": 5,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _store(tmp_path: Path, monkeypatch) -> LearningStore:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    (tmp_path / ".git").mkdir(exist_ok=True)
    return LearningStore()


def test_trusted_passing_gate_promotes_replacement_with_metadata_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    path, original = _seed_skill(tmp_path, store)
    script = _write_fixture_check(tmp_path)
    _write_sidecar(
        store,
        argv=[sys.executable, str(script), "{candidate}", "record the receipt"],
    )
    receipts: list[dict[str, Any]] = []
    monkeypatch.setattr(promotion, "trace_event", lambda **fields: receipts.append(fields))

    update = _skill(
        "Run the focused tests, verify the diff, check the final status, and record the receipt before handoff.",
        action="update",
    )
    assert apply_learning_result(result=update, cwd=str(tmp_path), store=store) == {
        "memories": 0,
        "skills": 1,
    }

    assert path.read_text(encoding="utf-8") != original
    assert len(store.skill_revisions(_SKILL_KEY)) == 2
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["event"] == "learning.skill_promotion"
    assert receipt["decision"] == "pass"
    assert receipt["check_id"] == "review-work-fixture"
    assert len(receipt["current_digest"]) == 64
    assert len(receipt["candidate_digest"]) == 64
    assert "record the receipt" not in {
        value for value in receipt.values() if isinstance(value, str)
    }


def test_trusted_failing_gate_preserves_bytes_and_revision_despite_candidate_fields(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    path, original = _seed_skill(tmp_path, store)
    script = _write_fixture_check(tmp_path)
    _write_sidecar(
        store,
        argv=[sys.executable, str(script), "{candidate}", "trusted-only-marker"],
        check_id="trusted-failure-gate",
    )
    receipts: list[dict[str, Any]] = []
    monkeypatch.setattr(promotion, "trace_event", lambda **fields: receipts.append(fields))

    update = _skill(
        "Run the focused tests, verify the diff, check the final status, and record the receipt before handoff.",
        action="update",
        check_id="candidate-selected-pass",
        argv=[sys.executable, "-c", "raise SystemExit(0)"],
    )
    assert apply_learning_result(result=update, cwd=str(tmp_path), store=store) == {
        "memories": 0,
        "skills": 0,
    }

    assert path.read_text(encoding="utf-8") == original
    assert len(store.skill_revisions(_SKILL_KEY)) == 1
    assert receipts[0]["decision"] == "fail"
    assert receipts[0]["check_id"] == "trusted-failure-gate"


def test_promotion_gate_execution_error_fails_closed_without_revision_change(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    path, original = _seed_skill(tmp_path, store)
    _write_sidecar(
        store,
        argv=["/definitely/missing/fcc-promotion-check", "{candidate}"],
        check_id="missing-adapter",
    )
    receipts: list[dict[str, Any]] = []
    monkeypatch.setattr(promotion, "trace_event", lambda **fields: receipts.append(fields))

    update = _skill(
        "Run the focused tests, verify the diff, check the final status, and record the receipt before handoff.",
        action="update",
    )
    assert apply_learning_result(result=update, cwd=str(tmp_path), store=store) == {
        "memories": 0,
        "skills": 0,
    }

    assert path.read_text(encoding="utf-8") == original
    assert len(store.skill_revisions(_SKILL_KEY)) == 1
    assert receipts[0]["decision"] == "error"
    assert receipts[0]["error_type"] == "PromotionCheckExecError"


def test_unregistered_skill_keeps_existing_structural_promotion_behavior(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    path, original = _seed_skill(tmp_path, store)
    receipts: list[dict[str, Any]] = []
    monkeypatch.setattr(promotion, "trace_event", lambda **fields: receipts.append(fields))

    update = _skill(
        "Run the focused tests, verify the diff, check the final status, and record the receipt before handoff.",
        action="update",
    )
    assert apply_learning_result(result=update, cwd=str(tmp_path), store=store) == {
        "memories": 0,
        "skills": 1,
    }

    assert path.read_text(encoding="utf-8") != original
    assert len(store.skill_revisions(_SKILL_KEY)) == 2
    assert receipts == []
