from free_claude_code.core.fault_attribution import (
    AttemptEvidence,
    FaultConfidence,
    FaultDomain,
    canonical_hash,
    classify_failure,
    media_metadata,
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


def test_media_metadata_counts_ordered_types_without_payloads() -> None:
    payload_marker = "do-not-retain-this-image"
    count, type_hash = media_metadata(
        {
            "messages": [
                {
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": payload_marker,
                            },
                        },
                        {
                            "type": "tool_result",
                            "content": [
                                {
                                    "type": "document",
                                    "source": {"media_type": "application/pdf"},
                                }
                            ],
                        },
                    ]
                }
            ]
        }
    )

    assert count == 2
    assert type_hash is not None
    assert payload_marker not in type_hash
    assert media_metadata({}) == (0, None)


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


def test_generic_transport_failure_does_not_blame_harness_without_proof() -> None:
    domain, confidence, codes = classify_failure(transport=True)

    assert domain is FaultDomain.UNKNOWN
    assert confidence is FaultConfidence.MEDIUM
    assert codes == ["transport_failure_ownership_unproven"]


def test_proven_local_transport_failure_can_blame_harness() -> None:
    domain, confidence, codes = classify_failure(harness_transport=True)

    assert domain is FaultDomain.HARNESS_TRANSPORT
    assert confidence is FaultConfidence.HIGH
    assert codes == ["local_transport_failure_proven"]


def test_explicit_upstream_error_outranks_generic_transport_signal() -> None:
    domain, confidence, codes = classify_failure(
        error_code="http_502",
        transport=True,
    )

    assert domain is FaultDomain.OPENCODE_GATEWAY
    assert confidence is FaultConfidence.HIGH
    assert codes == ["upstream_error:http_502"]


def test_attempt_receipt_is_metadata_only_and_serializable() -> None:
    evidence = AttemptEvidence(
        turn_id="turn_1",
        request_id="req_1",
        protocol="responses",
        provider="OPENCODE_GO",
        model="muse-spark-1.2-contributor",
        attempt_number=1,
        duration_ms=1234,
        time_to_first_token_ms=321,
        request_shape_hash=canonical_hash({"model": "muse-spark-1.2-contributor"}),
        requested_reasoning_control="on",
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
    assert receipt["duration_ms"] == 1234
    assert receipt["time_to_first_token_ms"] == 321
    assert "prompt" not in receipt
    assert "content" not in receipt
    assert receipt["requested_reasoning_effort"] == "high"
    assert receipt["requested_reasoning_control"] == "on"
    assert receipt["provider_visible_reasoning_summary"] is True


def test_attempt_receipt_defaults_timing_to_null_when_no_stream_started() -> None:
    evidence = AttemptEvidence(
        turn_id="turn_1",
        request_id=None,
        protocol="messages",
        provider="OPENCODE_GO",
        model="muse-spark-1.2-contributor",
        attempt_number=0,
    )

    receipt = evidence.as_dict()

    assert receipt["duration_ms"] is None
    assert receipt["time_to_first_token_ms"] is None


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
