import base64
import io

import pytest
from PIL import Image

from free_claude_code.core.visual_attachments import (
    VisualAttachmentError,
    validate_base64_source,
    validate_image_bytes,
)


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, format="PNG")
    return output.getvalue()


def test_receipt_is_safe_and_order_independent() -> None:
    data = _png()
    receipt = validate_base64_source({"media_type": "image/png", "data": base64.b64encode(data).decode()})
    assert receipt.width == 3 and receipt.height == 2
    assert receipt.attachment_id in receipt.card()
    assert base64.b64encode(data).decode() not in receipt.card()


@pytest.mark.parametrize("source", [{"media_type": "image/png", "data": "bad"}, {"media_type": "image/gif", "data": "x"}])
def test_invalid_or_unsupported_images_fail_before_upstream(source: dict[str, str]) -> None:
    with pytest.raises(VisualAttachmentError):
        validate_base64_source(source)


def test_media_type_mismatch_is_rejected() -> None:
    with pytest.raises(VisualAttachmentError, match="does not match"):
        validate_image_bytes(_png(), media_type="image/jpeg")
