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
        session_id_hash="session-hash",
        parent_session_id_hash="parent-session-hash",
        tool_call_ids=("call-1", "call-2"),
        tool_result_ids=("result-1", "result-2"),
        tool_call_batches=(("call-1",), ("call-2",)),
        tool_result_bindings=(
            ("call-1", "result-1"),
            ("call-2", "result-2"),
        ),
        reasoning_state_type="opaque",
        reasoning_state_hash="reasoning-hash",
        media_count=1,
        media_type_hash="image/png",
        media_disposition="preserved",
        learning_memory_ids=("memory-1",),
        skill_ids=("skill-1",),
        committed_tool_ids=("call-1",),
        resume_state_hash="resume-state-hash",
    )


def _state_with_batches(
    batches: tuple[tuple[str, ...], ...],
) -> CompactionState:
    call_ids = tuple(call_id for batch in batches for call_id in batch)
    result_ids = tuple(f"result-{index}" for index in range(1, len(call_ids) + 1))
    return replace(
        _state(),
        tool_call_ids=call_ids,
        tool_result_ids=result_ids,
        tool_call_batches=batches,
        tool_result_bindings=tuple(zip(call_ids, result_ids, strict=True)),
        committed_tool_ids=(call_ids[0],),
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
    "batches",
    [
        (("call-1",), ("call-2",)),
        (("call-1", "call-2"),),
    ],
    ids=["sequential", "parallel"],
)
def test_tool_identity_and_batch_shape_survive_compact_and_resume(
    batches: tuple[tuple[str, ...], ...],
) -> None:
    before = _state_with_batches(batches)
    compacted = replace(before)
    resumed = replace(compacted)

    for left, right in ((before, compacted), (compacted, resumed)):
        receipt = assert_compaction_continuity(left, right)
        assert receipt["invariants"]["tool_call_batches_preserved"] is True
        assert receipt["invariants"]["tool_result_bindings_preserved"] is True
        assert receipt["invariants"]["tool_identity_shape_valid"] is True
        assert receipt["invariants"]["resume_state_preserved"] is True


def test_compaction_rejects_swapped_tool_result_identity() -> None:
    after = replace(
        _state(),
        tool_result_bindings=(
            ("call-1", "result-2"),
            ("call-2", "result-1"),
        ),
    )

    receipt = validate_compaction_continuity(_state(), after)

    assert receipt["passed"] is False
    assert receipt["invariants"]["tool_result_bindings_preserved"] is False
    with pytest.raises(CompactionContinuityError, match="tool_result_bindings"):
        assert_compaction_continuity(_state(), after)


def test_compaction_rejects_sequential_parallel_shape_change() -> None:
    before = _state_with_batches((("call-1", "call-2"),))
    after = replace(before, tool_call_batches=(("call-1",), ("call-2",)))

    receipt = validate_compaction_continuity(before, after)

    assert receipt["passed"] is False
    assert receipt["invariants"]["tool_call_batches_preserved"] is False
    with pytest.raises(CompactionContinuityError, match="tool_call_batches"):
        assert_compaction_continuity(before, after)


def test_compaction_rejects_replayed_committed_side_effect() -> None:
    after = replace(
        _state(),
        tool_call_ids=("call-1", "call-2", "call-1"),
        tool_result_ids=("result-1", "result-2", "result-1-replay"),
        tool_call_batches=(("call-1",), ("call-2",), ("call-1",)),
        tool_result_bindings=(
            ("call-1", "result-1"),
            ("call-2", "result-2"),
            ("call-1", "result-1-replay"),
        ),
    )

    receipt = validate_compaction_continuity(_state(), after)

    assert receipt["passed"] is False
    assert receipt["invariants"]["committed_tools_not_replayed"] is False
    assert receipt["invariants"]["tool_identity_shape_valid"] is False
    with pytest.raises(CompactionContinuityError, match="committed_tools"):
        assert_compaction_continuity(_state(), after)


def test_resume_rejects_changed_opaque_continuation_state() -> None:
    after = replace(_state(), resume_state_hash="different-resume-state")

    receipt = validate_compaction_continuity(_state(), after)

    assert receipt["passed"] is False
    assert receipt["invariants"]["resume_state_preserved"] is False
    with pytest.raises(CompactionContinuityError, match="resume_state"):
        assert_compaction_continuity(_state(), after)


def test_compaction_rejects_reasoning_state_type_changes() -> None:
    after = replace(_state(), reasoning_state_type="visible_summary")

    receipt = validate_compaction_continuity(_state(), after)

    assert receipt["passed"] is False
    assert receipt["invariants"]["reasoning_state_preserved"] is False
    with pytest.raises(CompactionContinuityError, match="reasoning_state"):
        assert_compaction_continuity(_state(), after)


@pytest.mark.parametrize(
    "change,failed",
    [
        (replace(_state(), provider="anthropic"), "routing_preserved"),
        (
            replace(_state(), session_id_hash="different-session"),
            "session_relationship_preserved",
        ),
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
        (
            replace(_state(), committed_tool_ids=()),
            "committed_tools_not_replayed",
        ),
        (
            replace(_state(), learning_memory_ids=()),
            "learning_memory_not_duplicated",
        ),
        (replace(_state(), skill_ids=()), "skills_not_duplicated"),
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


@pytest.mark.parametrize(
    "field",
    ["prompt", "reasoning", "reasoning_content", "encrypted_content", "data"],
)
def test_compaction_state_parser_rejects_content_bearing_receipts(field: str) -> None:
    with pytest.raises(ValueError, match="metadata-only"):
        CompactionState.from_mapping({**_state().as_receipt(), field: "forbidden"})


def test_compaction_state_parser_rejects_unknown_state_instead_of_dropping_it() -> None:
    with pytest.raises(ValueError, match="unsupported compaction state fields"):
        CompactionState.from_mapping(
            {**_state().as_receipt(), "unsupported_state": "opaque-provider-blob"}
        )


def test_compaction_state_parser_rejects_unsupported_media_disposition() -> None:
    with pytest.raises(ValueError, match="unsupported media disposition"):
        CompactionState.from_mapping(
            {
                **_state().as_receipt(),
                "media_disposition": "rejected",
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
    receipt = validate_compaction_continuity(before, after)

    assert payload["passed"] is True
    assert receipt["passed"] is True
    assert payload["invariants"] == receipt["invariants"]


def test_checked_in_reasoning_effort_matrix_receipt_is_metadata_only() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "claude-reasoning-effort-matrix-2026-08-24.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert payload["claude"]["version"] == "2.1.228"
    assert payload["harness"]["package_version"] == "4.30.15"
    assert payload["matrix"]["efforts"] == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert payload["matrix"]["all_returncodes"] == [0, 0, 0, 0, 0]
    assert payload["reasoning"][-1]["requested"] == "max"
    assert payload["reasoning"][-1]["effective"] == "xhigh"
    assert payload["translation"]["requested_max_wire_value"] == "xhigh"
    assert "prompt" not in serialized
    assert "api_key" not in serialized
    assert "encrypted_content" not in serialized


def test_checked_in_reasoning_negative_receipt_does_not_claim_unsupported_efforts() -> (
    None
):
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "claude-reasoning-effort-negative-2026-08-24.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert payload["claude"]["advertised_efforts"] == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert payload["claude"]["requested_unavailable_efforts"] == [
        "off",
        "minimal",
    ]
    assert payload["probe"]["status"] == "unverified"
    assert payload["probe"]["provider_requests"] == 0
    assert "prompt" not in serialized
    assert "api_key" not in serialized
    assert "encrypted_content" not in serialized


def test_checked_in_reasoning_boundary_receipt_proves_off_and_minimal() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "claude-reasoning-boundaries-2026-08-24.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert payload["claude"]["version"] == "2.1.228"
    assert payload["harness"]["package_version"] == "4.30.19"
    assert payload["requests"] == {
        "messages_requests": 2,
        "completed_provider_turns": 2,
        "upstream_attempts_total": 2,
        "upstream_attempts_per_completed_turn": 1,
        "http_errors": 0,
        "terminal_event": "response.completed",
        "output_budget_tokens": 4096,
    }
    assert payload["routing"]["provider_model_ref"] == (
        "opencode_go/muse-spark-1.2-contributor"
    )
    assert payload["routing"]["upstream_protocol"] == "responses"
    assert [item["requested_control"] for item in payload["boundaries"]] == [
        "off",
        "minimal",
    ]
    assert [item["outcome"] for item in payload["boundaries"]] == [
        "completed",
        "completed",
    ]
    assert all(item["effective_effort"] == "minimal" for item in payload["boundaries"])
    assert all(item["provider_opaque_reasoning"] for item in payload["boundaries"])
    assert all(item["harness_thinking_block"] for item in payload["boundaries"])
    assert "prompt" not in serialized
    assert "content" not in serialized
    assert "api_key" not in serialized
    assert "encrypted_content" not in serialized


def test_checked_in_subagent_receipt_is_metadata_only() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "claude-subagent-2026-08-24.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert payload["surface"]["outcome"] == "passed"
    assert payload["surface"]["background"] == "not_run"
    assert payload["context"]["effective_tokens"] == 256_000
    assert payload["requests"]["foreground_run_in_background"] is False
    assert payload["routing"]["provider_model_ref"] == (
        "opencode_go/muse-spark-1.2-contributor"
    )
    assert payload["routing"]["upstream_protocol"] == "responses"
    assert "prompt" not in serialized
    assert "api_key" not in serialized
    assert "encrypted_content" not in serialized


def test_checked_in_background_session_receipt_preserves_unverified_boundary() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "claude-background-session-2026-08-24.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert payload["surface"] == {
        "name": "top_level_background_session",
        "outcome": "unverified",
        "background_handle_returned": True,
        "daemon_lifecycle": "disappeared_before_tool_execution",
        "claude_agents_after_probe": [],
    }
    assert payload["requests"]["fcc_messages_requests_observed"] == 0
    assert payload["routing"]["route_proven"] is False
    assert "prompt" not in serialized
    assert "api_key" not in serialized
    assert "encrypted_content" not in serialized


def test_checked_in_claude_compatibility_matrix_labels_surface_statuses() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "claude-compatibility-matrix-2026-08-24.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    statuses = {item["name"]: item["status"] for item in payload["surfaces"]}

    assert statuses["managed_resume"] == "passed"
    assert statuses["subagent_around_compaction"] == "unverified"
    assert statuses["candidate_client_upgrade"] == "skipped"
    assert payload["invariants"]["unverified_boundaries_are_labeled"] is True
    assert payload["invariants"]["raw_request_bodies_retained"] is False
    assert "prompt" not in serialized
    assert "content" not in serialized
    assert "api_key" not in serialized


def test_checked_in_managed_resume_receipt_is_metadata_only() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "claude-managed-resume-2026-08-24.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert payload["claude"]["version"] == "2.1.228"
    assert payload["surface"]["fresh"] == "passed"
    assert payload["surface"]["resume"] == "passed"
    assert payload["surface"]["fork"] == "passed"
    assert payload["context"]["effective_tokens"] == 256_000
    assert payload["requests"] == {
        "managed_turns": 3,
        "messages_requests": 6,
        "completed_provider_turns": 3,
        "upstream_attempts_total": 3,
        "upstream_attempts_per_turn": 1,
        "terminal_event": "response.completed",
    }
    assert payload["routing"] == {
        "provider_id": "opencode_go",
        "provider_model": "muse-spark-1.2-contributor",
        "provider_model_ref": "opencode_go/muse-spark-1.2-contributor",
        "client_wire_api": "messages",
        "upstream_protocol": "responses",
    }
    assert payload["reasoning"] == {
        "requested_effort": "high",
        "effective_effort": "high",
        "provider_reasoning_tokens": [154, 22, 10],
        "provider_reasoning_item": True,
        "provider_visible_reasoning_summary": False,
        "provider_reasoning_text": False,
        "provider_opaque_reasoning": True,
        "harness_thinking_block": True,
        "harness_thinking_delta": False,
    }
    assert "prompt" not in serialized
    assert "api_key" not in serialized
    assert "encrypted_content" not in serialized
