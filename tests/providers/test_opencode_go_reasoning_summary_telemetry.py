from free_claude_code.core.fault_attribution import AttemptEvidence
from free_claude_code.core.openai_responses.provider_stream import ResponsesProviderStream
from free_claude_code.providers.opencode_go.provider import _sync_responses_evidence


def test_visible_reasoning_summary_length_reaches_sanitized_attempt_receipt() -> None:
    stream = ResponsesProviderStream(
        message_id="msg_test",
        model="fixture-model",
        input_tokens=0,
    )
    evidence = AttemptEvidence(
        turn_id="turn_test",
        request_id="request_test",
        protocol="responses",
        provider="opencode_go",
        model="fixture-model",
        attempt_number=1,
    )

    assert stream.provider_visible_reasoning_summary_length is None

    stream.feed("response.reasoning_summary_text.delta", {"delta": "reason"})
    stream.feed("response.reasoning_summary_text.delta", {"delta": "ing"})
    _sync_responses_evidence(evidence, stream)

    assert stream.provider_visible_reasoning_summary is True
    assert stream.provider_visible_reasoning_summary_length == len("reasoning")
    assert evidence.provider_visible_reasoning_summary is True
    assert evidence.provider_visible_reasoning_summary_length == len("reasoning")
    assert evidence.as_dict()["provider_visible_reasoning_summary_length"] == len(
        "reasoning"
    )
