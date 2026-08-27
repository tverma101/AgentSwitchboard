"""Deterministic tests for the metadata-only native/Harness comparator."""

import pytest

from free_claude_code.core.fault_attribution import FaultConfidence, FaultDomain
from smoke.lib.native_harness_comparator import PathObservation, compare_paths


def _observation(path: str, **updates: object) -> PathObservation:
    value: dict[str, object] = {
        "scenario_id": "tool-turn",
        "path": path,
        "success": True,
        "protocol": "responses",
        "upstream_attempts": 1,
        "event_sequence": ["response.output_text.delta", "response.completed"],
        "terminal_event": "response.completed",
        "tool_call_count": 0,
        "stable_prefix_hash": "prefix-a",
        "request_shape_hash": "shape-a",
        "cache_read_tokens": 90,
        "input_tokens": 100,
        "ttft_ms": 10.0,
        "duration_ms": 100.0,
        "fault_domain": FaultDomain.UNKNOWN.value,
        "confidence": FaultConfidence.LOW.value,
        "evidence_codes": [],
    }
    value.update(updates)
    return PathObservation.from_mapping(value)


def test_both_success_produces_no_fault_owner() -> None:
    receipt = compare_paths(_observation("native"), _observation("harness"))

    assert receipt["attribution"] == {
        "fault_domain": None,
        "confidence": "high",
        "evidence_codes": ["both_paths_succeeded"],
    }
    assert receipt["comparison"]["success_match"] is True
    assert receipt["comparison"]["stable_prefix_match"] is True
    assert receipt["comparison"]["attempt_delta"] == 0


def test_protocol_mismatch_is_high_confidence_bridge_regression() -> None:
    receipt = compare_paths(
        _observation("native", protocol="responses"),
        _observation("harness", protocol="chat_completions"),
    )

    assert receipt["attribution"] == {
        "fault_domain": "harness_bridge",
        "confidence": "high",
        "evidence_codes": ["native_harness_protocol_mismatch"],
    }


def test_native_success_preserves_existing_harness_fault_attribution() -> None:
    receipt = compare_paths(
        _observation("native"),
        _observation(
            "harness",
            success=False,
            fault_domain=FaultDomain.OPENCODE_GATEWAY.value,
            confidence=FaultConfidence.HIGH.value,
            evidence_codes=["complete_tool_call_missing_terminal"],
        ),
    )

    assert receipt["attribution"] == {
        "fault_domain": "opencode_gateway",
        "confidence": "high",
        "evidence_codes": [
            "native_succeeded_harness_failed",
            "complete_tool_call_missing_terminal",
        ],
    }


def test_request_shape_divergence_attributes_bridge_without_guessing_model_fault() -> (
    None
):
    receipt = compare_paths(
        _observation("native"),
        _observation(
            "harness",
            success=False,
            request_shape_hash="shape-b",
        ),
    )

    assert receipt["attribution"] == {
        "fault_domain": "harness_bridge",
        "confidence": "high",
        "evidence_codes": [
            "native_succeeded_harness_failed",
            "request_shape_mismatch",
        ],
    }


def test_both_paths_same_upstream_fault_keeps_lower_confidence() -> None:
    receipt = compare_paths(
        _observation(
            "native",
            success=False,
            fault_domain=FaultDomain.OPENCODE_GATEWAY.value,
            confidence=FaultConfidence.HIGH.value,
            evidence_codes=["upstream_error:http_500"],
        ),
        _observation(
            "harness",
            success=False,
            fault_domain=FaultDomain.OPENCODE_GATEWAY.value,
            confidence=FaultConfidence.MEDIUM.value,
            evidence_codes=["stream_closed_without_terminal"],
        ),
    )

    assert receipt["attribution"]["fault_domain"] == "opencode_gateway"
    assert receipt["attribution"]["confidence"] == "medium"
    assert receipt["attribution"]["evidence_codes"][0] == "both_paths_same_fault_domain"


def test_native_failure_harness_success_does_not_blame_harness() -> None:
    receipt = compare_paths(
        _observation(
            "native",
            success=False,
            fault_domain=FaultDomain.OPENCODE_GATEWAY.value,
            confidence=FaultConfidence.HIGH.value,
        ),
        _observation("harness"),
    )

    assert receipt["attribution"] == {
        "fault_domain": "unknown",
        "confidence": "low",
        "evidence_codes": [
            "native_failed_harness_succeeded",
            "do_not_blame_harness_from_single_run",
        ],
    }


def test_raw_content_fields_are_rejected_recursively() -> None:
    with pytest.raises(ValueError, match="content-bearing"):
        PathObservation.from_mapping(
            {
                "scenario_id": "bad",
                "path": "native",
                "success": False,
                "protocol": "responses",
                "upstream_attempts": 1,
                "evidence": {"prompt": "secret"},
            }
        )


def test_comparator_rejects_different_scenarios() -> None:
    with pytest.raises(ValueError, match="same scenario_id"):
        compare_paths(
            _observation("native"),
            _observation("harness", scenario_id="different"),
        )
