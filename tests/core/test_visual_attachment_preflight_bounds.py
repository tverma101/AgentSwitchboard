from unittest.mock import patch

import pytest

from free_claude_code.core.visual_attachments import (
    MAX_IMAGE_BYTES,
    VisualAttachmentError,
    validate_base64_source,
)


def test_oversized_base64_is_rejected_before_decode() -> None:
    max_encoded_chars = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
    source = {"media_type": "image/png", "data": "A" * (max_encoded_chars + 1)}

    with (
        patch("free_claude_code.core.visual_attachments.base64.b64decode") as decode,
        pytest.raises(VisualAttachmentError, match="20 MiB"),
    ):
        validate_base64_source(source)

    decode.assert_not_called()


def test_unsupported_media_type_is_rejected_before_decode() -> None:
    source = {"media_type": "image/gif", "data": "AAAA"}

    with (
        patch("free_claude_code.core.visual_attachments.base64.b64decode") as decode,
        pytest.raises(VisualAttachmentError, match="Unsupported image media type"),
    ):
        validate_base64_source(source)

    decode.assert_not_called()
