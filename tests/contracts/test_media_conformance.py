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
    "source_data",
}


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
    path = (
        Path(__file__).parents[2] / "smoke" / "fixtures" / "media-conformance-v1.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema"] == "fcc.media-conformance.v1"
    assert payload["payload_policy"].startswith("metadata-only")
    cases = {case["id"]: case for case in payload["cases"]}
    assert set(cases) == _REQUIRED_CASES
    assert not _FORBIDDEN_PAYLOAD_KEYS.intersection(_walk_keys(payload))
    assert all(case["protocols"] for case in cases.values())
    assert all(case["expected"] for case in cases.values())


def test_media_conformance_corpus_preserves_explicit_rejection_boundaries() -> None:
    path = (
        Path(__file__).parents[2] / "smoke" / "fixtures" / "media-conformance-v1.json"
    )
    cases = {
        case["id"]: case
        for case in json.loads(path.read_text(encoding="utf-8"))["cases"]
    }

    for case_id in (
        "oversized-image",
        "unsupported-media-type",
        "malformed-base64-source",
    ):
        assert cases[case_id]["expected"] == "reject_before_upstream"
    assert cases["tool-result-image"]["expected"].endswith("typed_reject")
    assert cases["media-bearing-retry"]["expected"].startswith("one_")
