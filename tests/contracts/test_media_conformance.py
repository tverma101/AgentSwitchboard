"""Contract checks for the metadata-only media conformance corpus."""

import base64
import io
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from free_claude_code.application.errors import InvalidRequestError
from free_claude_code.core.anthropic import (
    OpenAIConversionError,
    build_base_request_body,
    dump_messages_request,
)
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.fault_attribution import media_metadata
from free_claude_code.core.openai_responses import (
    ResponsesConversionError,
    build_responses_provider_request,
)
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY
from free_claude_code.providers.opencode_go import (
    OpenCodeGoProvider,
    build_native_messages_body,
    protocol_for_model,
)

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


def _encoded_image(media_type: str) -> str:
    """Create a tiny in-memory image so tests do not check in image payloads."""
    image_format = media_type.removeprefix("image/").upper()
    output = io.BytesIO()
    Image.new("RGB", (1, 1), color=(23, 41, 59)).save(output, format=image_format)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _image_request(
    media_types: tuple[str, ...],
    *,
    model: str = "contract-test-model",
) -> MessagesRequest:
    content: list[dict[str, Any]] = []
    for index, media_type in enumerate(media_types):
        if index:
            content.append({"type": "text", "text": f"between-{index}"})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": _encoded_image(media_type),
                },
            }
        )
    return MessagesRequest.model_validate(
        {
            "model": model,
            "messages": [{"role": "user", "content": content}],
        }
    )


def _url_image_request() -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": "contract-test-model",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "https://example.test/image.jpg",
                            },
                        }
                    ],
                }
            ],
        }
    )


def _tool_result_image_request(
    *, model: str = "contract-test-model"
) -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": model,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_screenshot",
                            "name": "computer",
                            "input": {"action": "screenshot"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_screenshot",
                            "content": [
                                {"type": "text", "text": "Screenshot captured."},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": _encoded_image("image/png"),
                                    },
                                },
                            ],
                        }
                    ],
                },
            ],
        }
    )


def _go_responses_body(request: MessagesRequest) -> dict[str, Any]:
    return OpenCodeGoProvider._build_responses_body(
        request,
        reasoning=DEFAULT_REASONING_POLICY,
    )


def _wire_media(value: Any) -> list[tuple[str, str | None]]:
    """Extract media markers from known wire shapes without inspecting payloads."""
    found: list[tuple[str, str | None]] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            block_type = item.get("type")
            if block_type == "image":
                source = item.get("source")
                media_type = (
                    source.get("media_type") if isinstance(source, dict) else None
                )
                found.append(
                    ("image", media_type if isinstance(media_type, str) else None)
                )
            elif block_type == "image_url":
                image_url = item.get("image_url")
                url = image_url.get("url") if isinstance(image_url, dict) else image_url
                found.append(("image_url", _data_url_media_type(url)))
            elif block_type == "input_image":
                found.append(
                    ("input_image", _data_url_media_type(item.get("image_url")))
                )
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def _data_url_media_type(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("data:"):
        return None
    media_type, separator, _ = value[5:].partition(";")
    return media_type if separator and media_type else None


@pytest.mark.parametrize(
    ("builder", "wire_type"),
    [
        (build_base_request_body, "image_url"),
        (
            lambda request: build_responses_provider_request(
                request,
                reasoning=DEFAULT_REASONING_POLICY,
            ),
            "input_image",
        ),
    ],
)
def test_url_image_is_preserved_by_url_capable_adapters(
    builder: Any,
    wire_type: str,
) -> None:
    body = builder(_url_image_request())

    assert _wire_media(body) == [(wire_type, None)]
    assert "https://example.test/image.jpg" in json.dumps(body)


@pytest.mark.parametrize(
    ("route", "builder", "wire_type", "model"),
    [
        ("anthropic_messages", dump_messages_request, "image", "contract-test-model"),
        ("openai_chat", build_base_request_body, "image_url", "contract-test-model"),
        (
            "openai_responses",
            lambda request: build_responses_provider_request(
                request,
                reasoning=DEFAULT_REASONING_POLICY,
            ),
            "input_image",
            "contract-test-model",
        ),
        ("opencode_go_messages", build_native_messages_body, "image", "qwen3.7-plus"),
        ("opencode_go_responses", _go_responses_body, "input_image", "gpt-5.6-luna"),
    ],
)
def test_supported_adapters_preserve_order_and_media_count(
    route: str,
    builder: Any,
    wire_type: str,
    model: str,
) -> None:
    del route
    request = _image_request(
        ("image/png", "image/jpeg", "image/webp"),
        model=model,
    )
    before_count, before_hash = media_metadata(request.model_dump(mode="python"))

    body = builder(request)
    wire_media = _wire_media(body)

    assert before_count == 3
    assert before_hash is not None
    assert len(wire_media) == before_count
    assert [marker[0] for marker in wire_media] == [wire_type] * before_count
    assert [marker[1] for marker in wire_media] == [
        "image/png",
        "image/jpeg",
        "image/webp",
    ]
    assert request.model_dump(mode="python")["messages"][0]["content"][1]["type"] == (
        "text"
    )


@pytest.mark.parametrize(
    ("builder", "error_type"),
    [
        (build_base_request_body, OpenAIConversionError),
        (
            lambda request: build_responses_provider_request(
                request,
                reasoning=DEFAULT_REASONING_POLICY,
            ),
            ResponsesConversionError,
        ),
    ],
)
def test_openai_bridges_reject_tool_result_media_before_upstream(
    builder: Any,
    error_type: type[Exception],
) -> None:
    request = _tool_result_image_request()
    before_count, before_hash = media_metadata(request.model_dump(mode="python"))

    with pytest.raises(error_type, match="media"):
        builder(request)

    assert before_count == 1
    assert before_hash is not None
    request_data = request.model_dump(mode="python")
    assert request_data["messages"][1]["content"][0]["tool_use_id"] == (
        "call_screenshot"
    )


def test_native_routes_preserve_tool_result_image_association() -> None:
    request = _tool_result_image_request(model="qwen3.7-plus")
    body = build_native_messages_body(request)

    result = body["messages"][1]["content"][0]
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "call_screenshot"
    image = result["content"][1]
    assert image["type"] == "image"
    assert image["source"]["media_type"] == "image/png"
    assert protocol_for_model("qwen3.7-plus").value == "messages"


@pytest.mark.parametrize(
    "source",
    [
        {"type": "base64", "media_type": "image/png", "data": "not-base64"},
        {"type": "base64", "media_type": "image/gif", "data": "AAAA"},
    ],
)
def test_supported_base64_routes_reject_invalid_media_before_upstream(
    source: dict[str, str],
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "qwen3.7-plus",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "image", "source": source}],
                }
            ],
        }
    )

    with pytest.raises((OpenAIConversionError, ResponsesConversionError)):
        build_base_request_body(request)
    with pytest.raises(ResponsesConversionError):
        build_responses_provider_request(
            request,
            reasoning=DEFAULT_REASONING_POLICY,
        )
    with pytest.raises(InvalidRequestError):
        build_native_messages_body(request)


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
