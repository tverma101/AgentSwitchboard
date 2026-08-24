from free_claude_code.core.fault_attribution import (
    AttemptEvidence,
    FaultConfidence,
    FaultDomain,
    canonical_hash,
    classify_failure,
    stable_prefix_hash,
)


def test_hashes_are_deterministic_and_exclude_conversation_suffix() -> None:
    first = {
        "model": "muse-spark-1.2-contributor",
        "instructions": "stable",
        "tools": [{"name": "lookup"}],
        "input": [
            {"role": "user", "content": "prefix"},
            {"role": "user", "content": "a"},
        ],
    }
    second = {
        **first,
        "input": [
            {"role": "user", "content": "prefix"},
            {"role": "user", "content": "b"},
        ],
    }

    assert canonical_hash(first) == canonical_hash({**first})
    assert stable_prefix_hash(first) == stable_prefix_hash(second)
    assert stable_prefix_hash(first) != canonical_hash(first)


def test_fault_classifier_prioritizes_bridge_and_model_output_evidence() -> None:
    domain, confidence, codes = classify_failure(bridge=True, transport=True)
    assert (domain, confidence, codes) == (
        FaultDomain.HARNESS_BRIDGE,
        FaultConfidence.HIGH,
        ["bridge_conversion_error"],
    )

    domain, confidence, codes = classify_failure(
        error_code="invalid_tool_arguments",
        invalid_tool_json=True,
        output_committed=True,
    )
    assert domain is FaultDomain.MODEL_OUTPUT
    assert confidence is FaultConfidence.MEDIUM
    assert codes == [
        "complete_event_invalid_tool_json",
        "downstream_output_already_committed",
    ]


def test_attempt_receipt_is_metadata_only_and_serializable() -> None:
    evidence = AttemptEvidence(
        turn_id="turn_1",
        request_id="req_1",
        protocol="responses",
        provider="OPENCODE_GO",
        model="muse-spark-1.2-contributor",
        attempt_number=1,
        request_shape_hash=canonical_hash({"model": "muse-spark-1.2-contributor"}),
        requested_reasoning_effort="high",
        requested_reasoning_budget_tokens=2_048,
        provider_reasoning_item=True,
        provider_visible_reasoning_summary=True,
        harness_thinking_block=True,
    )
    evidence.add_event("response.output_text.delta", byte_count=17)
    evidence.add_event("response.output_text.delta", byte_count=3)
    receipt = evidence.as_dict()

    assert receipt["fault_domain"] == "unknown"
    assert receipt["event_types"] == [
        "response.output_text.delta",
        "response.output_text.delta",
    ]
    assert receipt["bytes_received"] == 20
    assert "prompt" not in receipt
    assert "content" not in receipt
    assert receipt["requested_reasoning_effort"] == "high"
    assert receipt["provider_visible_reasoning_summary"] is True


def test_attempt_receipt_event_sequence_is_bounded() -> None:
    evidence = AttemptEvidence(
        turn_id="turn_1",
        request_id=None,
        protocol="responses",
        provider="OPENCODE_GO",
        model="muse-spark-1.2-contributor",
        attempt_number=1,
    )

    for index in range(5_000):
        evidence.add_event(f"event_{index}")

    assert len(evidence.event_types) == 4_096
    assert evidence.event_types[-1] == "event_sequence_truncated"
