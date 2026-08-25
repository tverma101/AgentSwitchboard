from free_claude_code.core.fault_attribution import AttemptEvidence
from free_claude_code.core.openai_responses.provider_stream import (
    ResponsesProviderStream,
)
from free_claude_code.providers.opencode_go.provider import (
    _sync_responses_evidence,
)


def test_summary_length_reaches_receipt_without_summary_text() -> None:
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

    stream.feed("response.reasoning_summary_text.delta", {"delta": "reason"})
    stream.feed("response.reasoning_summary_text.delta", {"delta": "ing"})
    _sync_responses_evidence(evidence, stream)
    receipt = evidence.as_dict()

    assert receipt["provider_visible_reasoning_summary"] is True
    assert receipt["provider_visible_reasoning_summary_length"] == len("reasoning")
    assert "reasoning" not in {
        value for value in receipt.values() if isinstance(value, str)
    }
