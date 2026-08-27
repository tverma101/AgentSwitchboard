import base64
import io

import pytest
from PIL import Image

from free_claude_code.core.visual_attachments import (
    VisualAttachmentError,
    validate_base64_source,
    validate_image_bytes,
    validate_image_url,
)


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, format="PNG")
    return output.getvalue()


def test_receipt_is_safe_and_order_independent() -> None:
    data = _png()
    receipt = validate_base64_source(
        {"media_type": "image/png", "data": base64.b64encode(data).decode()}
    )
    assert receipt.width == 3 and receipt.height == 2
    assert receipt.attachment_id in receipt.card()
    assert base64.b64encode(data).decode() not in receipt.card()


@pytest.mark.parametrize(
    "source",
    [
        {"media_type": "image/png", "data": "bad"},
        {"media_type": "image/gif", "data": "x"},
    ],
)
def test_invalid_or_unsupported_images_fail_before_upstream(
    source: dict[str, str],
) -> None:
    with pytest.raises(VisualAttachmentError):
        validate_base64_source(source)


def test_media_type_mismatch_is_rejected() -> None:
    with pytest.raises(VisualAttachmentError, match="does not match"):
        validate_image_bytes(_png(), media_type="image/jpeg")


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/image.png",
        "data:image/png;base64,abc",
        "https://user:password@example.test/image.png",
        "https://example.test/image with-space.png",
        "https://",
    ],
)
def test_image_url_validator_rejects_non_network_or_credentialed_sources(
    url: str,
) -> None:
    with pytest.raises(VisualAttachmentError):
        validate_image_url(url)


def test_image_url_validator_accepts_http_and_https_without_fetching() -> None:
    assert validate_image_url("http://example.test/image.png") == (
        "http://example.test/image.png"
    )
    assert validate_image_url("https://example.test/image.png") == (
        "https://example.test/image.png"
    )
