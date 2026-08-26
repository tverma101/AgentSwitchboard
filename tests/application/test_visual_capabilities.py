import pytest

from free_claude_code.application.errors import VisualCapabilityError
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.application.visual_capabilities import (
    validate_visual_capability,
    validate_visual_input,
)
from free_claude_code.core.anthropic.models import MessagesRequest

_PNG_DATA = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _request(*, content: list[dict[str, object]]) -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": "provider-model",
            "messages": [{"role": "user", "content": content}],
        }
    )


def test_known_nonvision_model_fails_before_upstream() -> None:
    with pytest.raises(VisualCapabilityError, match="before upstream I/O"):
        validate_visual_capability(
            _request(
                content=[
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _PNG_DATA,
                        },
                    }
                ]
            ),
            model_info=ProviderModelInfo("provider-model", supports_vision=False),
            model_ref="provider/provider-model",
        )


def test_known_image_types_are_enforced_without_rejecting_urls() -> None:
    info = ProviderModelInfo(
        "provider-model",
        supports_vision=True,
        accepted_image_types=("image/jpeg",),
    )
    with pytest.raises(VisualCapabilityError, match="image/png"):
        validate_visual_capability(
            _request(
                content=[
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _PNG_DATA,
                        },
                    }
                ]
            ),
            model_info=info,
            model_ref="provider/provider-model",
        )

    validate_visual_capability(
        _request(
            content=[
                {
                    "type": "image",
                    "source": {"type": "url", "url": "https://example.test/a"},
                }
            ]
        ),
        model_info=info,
        model_ref="provider/provider-model",
    )


def test_unknown_capability_metadata_fails_closed() -> None:
    with pytest.raises(VisualCapabilityError, match="metadata not confirmed"):
        validate_visual_capability(
            _request(
                content=[
                    {
                        "type": "image",
                        "source": {"type": "url", "url": "https://example.test/a"},
                    }
                ]
            ),
            model_info=ProviderModelInfo("provider-model"),
            model_ref="provider/provider-model",
        )


def test_missing_model_metadata_fails_closed() -> None:
    with pytest.raises(VisualCapabilityError, match="metadata unavailable"):
        validate_visual_capability(
            _request(
                content=[
                    {
                        "type": "image",
                        "source": {"type": "url", "url": "https://example.test/a"},
                    }
                ]
            ),
            model_info=None,
            model_ref="provider/provider-model",
        )


def test_tool_result_image_is_not_silently_missed() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "provider-model",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": _PNG_DATA,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )

    with pytest.raises(VisualCapabilityError):
        validate_visual_capability(
            request,
            model_info=ProviderModelInfo("provider-model", supports_vision=False),
            model_ref="provider/provider-model",
        )


def test_visual_input_receipt_validates_nested_images_without_payloads() -> None:
    receipt = validate_visual_input(
        _request(
            content=[
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": _PNG_DATA,
                    },
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "https://example.test/nested.png",
                            },
                        }
                    ],
                },
            ]
        )
    )

    assert receipt is not None
    assert receipt.image_count == 2
    assert receipt.url_image_count == 1
    assert receipt.as_dict()["inline_image_count"] == 1
    assert receipt.attachments[0].byte_count > 0
    serialized = str(receipt.as_dict())
    assert _PNG_DATA not in serialized
    assert "example.test" not in serialized


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/private.png",
        "data:image/png;base64,not-a-network-url",
        "https://user:password@example.test/image.png",
        "https://example.test/image with-space.png",
        "https://",
    ],
)
def test_visual_input_rejects_unsafe_image_urls(url: str) -> None:
    with pytest.raises(VisualCapabilityError, match="before upstream I/O"):
        validate_visual_input(
            _request(
                content=[
                    {
                        "type": "image",
                        "source": {"type": "url", "url": url},
                    }
                ]
            )
        )


def test_visual_input_rejects_invalid_inline_image_before_upstream() -> None:
    with pytest.raises(VisualCapabilityError, match="Image attachment rejected"):
        validate_visual_input(
            _request(
                content=[
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "not-valid-base64",
                        },
                    }
                ]
            )
        )


def test_visual_capability_returns_admitted_receipt() -> None:
    receipt = validate_visual_capability(
        _request(
            content=[
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": _PNG_DATA,
                    },
                }
            ]
        ),
        model_info=ProviderModelInfo("provider-model", supports_vision=True),
        model_ref="provider/provider-model",
    )

    assert receipt is not None
    assert receipt.image_count == 1
