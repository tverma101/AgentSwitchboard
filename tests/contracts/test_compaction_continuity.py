"""Deterministic semantic continuity checks for compaction receipts."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from smoke.lib.compaction_continuity import (
    CompactionContinuityError,
    CompactionState,
    assert_compaction_continuity,
    validate_compaction_continuity,
)


def _state() -> CompactionState:
    return CompactionState(
        provider="opencode_go",
        model="muse-spark-1.2-contributor",
        protocol="responses",
        system_tool_schema_hash="schema-hash",
        message_shape_hash="message-shape",
        tool_call_ids=("call-1", "call-2"),
        tool_result_ids=("result-1", "result-2"),
        reasoning_state_type="opaque",
        reasoning_state_hash="reasoning-hash",
        media_count=1,
        media_type_hash="image/png",
        learning_memory_ids=("memory-1",),
        skill_ids=("skill-1",),
        committed_tool_ids=("call-1",),
    )


def test_compaction_receipt_passes_when_structural_state_is_preserved() -> None:
    receipt = assert_compaction_continuity(_state(), _state())

    assert receipt["schema"] == "fcc.compaction-continuity.v1"
    assert receipt["passed"] is True
    assert all(receipt["invariants"].values())
    serialized = json.dumps(receipt)
    assert "prompt" not in serialized
    assert "content" not in serialized
    assert "reasoning-hash" in serialized


@pytest.mark.parametrize(
    "change,failed",
    [
        (replace(_state(), provider="anthropic"), "routing_preserved"),
        (replace(_state(), reasoning_state_hash=None), "reasoning_state_preserved"),
        (replace(_state(), media_count=0), "media_preserved"),
        (
            replace(_state(), learning_memory_ids=("memory-1", "memory-1")),
            "learning_memory_not_duplicated",
        ),
        (
            replace(_state(), committed_tool_ids=("call-1", "call-1")),
            "committed_tools_not_replayed",
        ),
        (replace(_state(), retry_attempts=3), "retry_amplification_bounded"),
    ],
)
def test_compaction_receipt_rejects_semantic_regressions(
    change: CompactionState, failed: str
) -> None:
    receipt = validate_compaction_continuity(_state(), change)

    assert receipt["passed"] is False
    assert receipt["invariants"][failed] is False
    with pytest.raises(CompactionContinuityError, match=failed):
        assert_compaction_continuity(_state(), change)


def test_compaction_state_parser_rejects_content_bearing_receipts() -> None:
    with pytest.raises(ValueError, match="metadata-only"):
        CompactionState.from_mapping(
            {
                "provider": "opencode_go",
                "model": "muse-spark-1.2-contributor",
                "protocol": "responses",
                "system_tool_schema_hash": "schema",
                "message_shape_hash": "shape",
                "prompt": "must not be persisted",
            }
        )


def test_compaction_state_parser_round_trips_sanitized_metadata() -> None:
    state = _state()

    assert CompactionState.from_mapping(state.as_receipt()) == state


def test_checked_in_synthetic_compaction_receipt_matches_the_gate() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / ("compaction-continuity-synthetic.json")
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    before = CompactionState.from_mapping(payload["before"])
    after = CompactionState.from_mapping(payload["after"])

    assert validate_compaction_continuity(before, after)["passed"] is True
