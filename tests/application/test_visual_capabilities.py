import pytest

from free_claude_code.application.errors import VisualCapabilityError
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.application.visual_capabilities import validate_visual_capability
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
