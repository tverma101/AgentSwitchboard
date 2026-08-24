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


def test_checked_in_muse_auto_compact_receipt_is_current_and_metadata_only() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "muse-auto-compact-2026-08-24.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert payload["claude"]["launcher"] == "fccdanger"
    assert payload["claude"]["version"] == "2.1.228"
    assert payload["harness"]["package_version"] == "4.30.7"
    assert payload["context"]["effective_tokens"] == 50_000
    assert payload["compaction"] == {
        "trigger": "auto",
        "result": "success",
        "compact_boundary_observed": True,
        "compact_metadata_observed": True,
        "manual_compact_command_sent": False,
    }
    assert payload["post_compaction"]["tool_call_count"] == 1
    assert payload["routing"]["provider_model_ref"] == (
        "opencode_go/muse-spark-1.2-contributor"
    )
    assert payload["routing"]["upstream_protocol"] == "responses"
    assert "prompt" not in serialized
    assert "api_key" not in serialized
    assert "encrypted_content" not in serialized


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
    assert payload["harness"]["package_version"] == "4.30.7"
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


def test_checked_in_claude_compatibility_matrix_labels_unverified_surfaces() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "claude-compatibility-matrix-2026-08-24.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    statuses = {item["name"]: item["status"] for item in payload["surfaces"]}

    assert statuses["fresh_fccdanger"] == "passed"
    assert statuses["managed_resume"] == "passed"
    assert statuses["top_level_background_session"] == "unverified"
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
