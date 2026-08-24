"""Contract checks for the metadata-only media conformance corpus."""

import json
from pathlib import Path
from typing import Any

_REQUIRED_CASES = {
    "single-png-base64",
    "single-jpeg-base64",
    "single-webp-base64",
    "url-image",
    "interleaved-multiple-images",
    "tool-result-image",
    "thinking-history-with-image",
    "parallel-tools-with-image",
    "oversized-image",
    "unsupported-media-type",
    "malformed-base64-source",
    "media-bearing-retry",
    "anthropic-messages-to-openai-chat",
    "anthropic-messages-to-openai-responses",
    "native-anthropic-messages",
    "opencode-go-model-route",
}
_FORBIDDEN_PAYLOAD_KEYS = {
    "base64",
    "bytes",
    "content",
    "data",
    "image_bytes",
    "payload",
    "prompt",
    "response",
    "source_data",
    "tool_arguments",
}
_REQUIRED_RECEIPT_FIELDS = ["media_count", "media_type_hash"]
_REQUIRED_PROTOCOL_CASES = {
    "anthropic-messages-to-openai-chat": {"anthropic_messages", "openai_chat"},
    "anthropic-messages-to-openai-responses": {
        "anthropic_messages",
        "openai_responses",
    },
    "native-anthropic-messages": {"anthropic_messages"},
    "opencode-go-model-route": {"opencode_go_messages", "opencode_go_responses"},
}


def _load_corpus() -> dict[str, Any]:
    path = (
        Path(__file__).parents[2] / "smoke" / "fixtures" / "media-conformance-v1.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _cases() -> dict[str, dict[str, Any]]:
    return {case["id"]: case for case in _load_corpus()["cases"]}


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [
            *(str(key) for key in value),
            *[key for child in value.values() for key in _walk_keys(child)],
        ]
    if isinstance(value, list):
        return [key for child in value for key in _walk_keys(child)]
    return []


def test_media_conformance_corpus_is_complete_and_payload_free() -> None:
    payload = _load_corpus()

    assert payload["schema"] == "fcc.media-conformance.v1"
    assert payload["payload_policy"].startswith("metadata-only")
    cases = {case["id"]: case for case in payload["cases"]}
    assert set(cases) == _REQUIRED_CASES
    assert not _FORBIDDEN_PAYLOAD_KEYS.intersection(_walk_keys(payload))
    assert all(case["protocols"] for case in cases.values())
    assert all(case["expected"] for case in cases.values())

    receipt_contract = payload["receipt_contract"]
    assert receipt_contract["required_fields"] == _REQUIRED_RECEIPT_FIELDS
    assert receipt_contract["media_count_semantics"] == "before_and_after_conversion"
    assert receipt_contract["hash_input"] == (
        "ordered block type and declared media type"
    )
    assert receipt_contract["payload_free"] is True
    assert set(receipt_contract["forbidden_keys"]) == _FORBIDDEN_PAYLOAD_KEYS

    assert payload["invariants"] == {
        "source_order": "preserve_on_success",
        "zero_media_after_conversion": "typed_reject",
        "unsupported_media_route": "reject_before_upstream",
        "tool_result_association": "tool_use_id",
        "retry_side_effects": "at_most_one_per_logical_request",
    }


def test_media_conformance_corpus_has_ordered_media_goldens() -> None:
    cases = _cases()

    for case in cases.values():
        golden = case["golden"]
        ordered_media_types = golden["ordered_media_types"]
        assert golden["media_count"] == len(ordered_media_types)
        assert golden["media_count"] > 0
        assert golden["association"] in {"none", "tool_use_id"}
        assert golden["source_order"] in {
            "preserve_on_success",
            "not_applicable_on_reject",
        }

    assert cases["interleaved-multiple-images"]["golden"]["ordered_media_types"] == [
        "image/png",
        "image/webp",
    ]
    assert cases["interleaved-multiple-images"]["golden"]["interleaved_text"] is True


def test_media_conformance_corpus_covers_protocol_pairs() -> None:
    cases = _cases()

    for case_id, protocols in _REQUIRED_PROTOCOL_CASES.items():
        assert protocols.issubset(cases[case_id]["protocols"])

    assert cases["media-bearing-retry"]["protocols"] == [
        "opencode_go_responses",
        "opencode_go_messages",
    ]


def test_media_conformance_corpus_preserves_explicit_rejection_boundaries() -> None:
    cases = _cases()

    for case_id in (
        "oversized-image",
        "unsupported-media-type",
        "malformed-base64-source",
    ):
        assert cases[case_id]["expected"] == "reject_before_upstream"
        assert cases[case_id]["golden"]["upstream_attempts"] == 0
        assert cases[case_id]["golden"]["source_order"] == ("not_applicable_on_reject")
    assert cases["tool-result-image"]["expected"].endswith("typed_reject")
    assert cases["media-bearing-retry"]["expected"].startswith("one_")


def test_media_conformance_corpus_preserves_tool_association_and_retry_identity() -> (
    None
):
    cases = _cases()

    for case_id in (
        "tool-result-image",
        "parallel-tools-with-image",
        "anthropic-messages-to-openai-chat",
        "anthropic-messages-to-openai-responses",
        "native-anthropic-messages",
    ):
        assert cases[case_id]["golden"]["association"] == "tool_use_id"

    assert cases["tool-result-image"]["context"] == "computer_use_screenshot"

    retry_golden = cases["media-bearing-retry"]["golden"]
    assert retry_golden["max_receipts_per_logical_request"] == 1
    assert retry_golden["max_side_effects_per_logical_request"] == 1
