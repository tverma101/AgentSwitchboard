"""Validated, metadata-only helpers for visual input and local receipts."""

import base64
import binascii
import hashlib
import io
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

SUPPORTED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class VisualAttachmentError(ValueError):
    """A visual attachment cannot be safely admitted to an upstream request."""


@dataclass(frozen=True, slots=True)
class VisualAttachmentReceipt:
    """Safe attachment metadata; image bytes are intentionally never retained."""

    attachment_id: str
    media_type: str
    byte_count: int
    width: int
    height: int
    label: str = "clipboard-image"

    def as_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "media_type": self.media_type,
            "byte_count": self.byte_count,
            "width": self.width,
            "height": self.height,
            "label": self.label,
        }

    def card(self) -> str:
        size = f"{self.byte_count / 1024:.0f} KiB"
        return (
            f"[img {self.attachment_id} · {self.label} · "
            f"{self.width}\u00d7{self.height} {self.media_type.removeprefix('image/').upper()} "
            f"· {size} · attached]"
        )


def validate_image_url(url: object) -> str:
    """Validate an image URL without resolving or fetching the target."""
    if not isinstance(url, str) or not url:
        raise VisualAttachmentError("Image URL source requires a non-empty URL")
    if any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in url
    ):
        raise VisualAttachmentError(
            "Image URL source must not contain whitespace or control characters"
        )
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        _port = parsed.port
    except ValueError as exc:
        raise VisualAttachmentError(
            "Image URL source must be a valid absolute HTTP(S) URL"
        ) from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise VisualAttachmentError(
            "Image URL source must use the http or https scheme"
        )
    if not parsed.netloc or hostname is None:
        raise VisualAttachmentError(
            "Image URL source must be a valid absolute HTTP(S) URL"
        )
    if parsed.username is not None or parsed.password is not None:
        raise VisualAttachmentError("Image URL source must not contain credentials")
    return url


def validate_image_bytes(
    data: bytes,
    *,
    media_type: str,
    label: str = "clipboard-image",
    max_bytes: int = MAX_IMAGE_BYTES,
) -> VisualAttachmentReceipt:
    """Validate bytes and return a redacted receipt suitable for logs/UI."""
    if media_type not in SUPPORTED_IMAGE_TYPES:
        raise VisualAttachmentError(f"Unsupported image media type: {media_type}")
    if not 1 <= max_bytes <= MAX_IMAGE_BYTES:
        raise ValueError(f"max_bytes must be between 1 and {MAX_IMAGE_BYTES}")
    if not data:
        raise VisualAttachmentError("Image data is empty")
    if len(data) > max_bytes:
        raise VisualAttachmentError(
            f"Image exceeds the {max_bytes / (1024 * 1024):g} MiB limit"
        )
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            actual_type = image.get_format_mimetype()
    except (OSError, ValueError) as exc:
        raise VisualAttachmentError("Image bytes are corrupt or unreadable") from exc
    if actual_type != media_type:
        raise VisualAttachmentError("Image media type does not match its bytes")
    digest = hashlib.sha256(data).hexdigest()[:8]
    return VisualAttachmentReceipt(digest, media_type, len(data), width, height, label)


def validate_base64_source(source: dict[str, Any]) -> VisualAttachmentReceipt:
    """Validate an Anthropic base64 source without exposing its payload."""
    encoded = source.get("data")
    media_type = source.get("media_type")
    if not isinstance(encoded, str) or not isinstance(media_type, str):
        raise VisualAttachmentError("Base64 image requires media_type and data")
    if media_type not in SUPPORTED_IMAGE_TYPES:
        raise VisualAttachmentError(f"Unsupported image media type: {media_type}")

    # Base64 expands three input bytes into four ASCII characters. Reject an
    # impossible-to-fit payload before allocating its decoded copy; the
    # decoded-byte check in validate_image_bytes remains authoritative.
    max_encoded_chars = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
    if len(encoded) > max_encoded_chars:
        raise VisualAttachmentError(
            f"Image exceeds the {MAX_IMAGE_BYTES / (1024 * 1024):g} MiB limit"
        )
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise VisualAttachmentError("Image base64 is invalid") from exc
    return validate_image_bytes(data, media_type=media_type)
