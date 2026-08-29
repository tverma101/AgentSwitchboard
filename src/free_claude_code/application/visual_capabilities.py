"""Provider-independent validation for model visual-input capabilities."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from free_claude_code.application.capabilities import (
    Capability,
    required_capabilities_for_messages,
)
from free_claude_code.application.errors import VisualCapabilityError
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.core.anthropic.content import get_block_attr, get_block_type
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.visual_attachments import (
    VisualAttachmentError,
    VisualAttachmentReceipt,
    validate_base64_source,
    validate_image_url,
)


@dataclass(frozen=True, slots=True)
class VisualInputReceipt:
    """Metadata-only summary of image input admitted at the API boundary."""

    attachments: tuple[VisualAttachmentReceipt, ...]
    url_image_count: int

    @property
    def image_count(self) -> int:
        """Return the total number of image blocks, regardless of source."""
        return len(self.attachments) + self.url_image_count

    def as_dict(self) -> dict[str, object]:
        """Return a trace-safe representation without image payloads or URLs."""
        return {
            "image_count": self.image_count,
            "inline_image_count": len(self.attachments),
            "inline_image_bytes": sum(
                attachment.byte_count for attachment in self.attachments
            ),
            "url_image_count": self.url_image_count,
            "attachments": [attachment.as_dict() for attachment in self.attachments],
        }


def validate_visual_input(request: MessagesRequest) -> VisualInputReceipt | None:
    """Validate every image block before any provider is constructed.

    Inline images are decoded and inspected transiently. URL sources are only
    syntax-checked; fetching remains the responsibility of the upstream
    protocol/provider and is never performed by ingress validation.
    """
    attachments: list[VisualAttachmentReceipt] = []
    url_image_count = 0
    for block in _iter_image_blocks(request.messages):
        source = get_block_attr(block, "source")
        if not isinstance(source, Mapping):
            raise VisualCapabilityError(
                "Image source must be an object; the request was rejected "
                "before upstream I/O."
            )
        source_type = source.get("type")
        try:
            if source_type == "base64":
                attachments.append(validate_base64_source(dict(source)))
            elif source_type == "url":
                validate_image_url(source.get("url"))
                url_image_count += 1
            else:
                raise VisualAttachmentError(
                    f"Unsupported image source type {source_type!r}"
                )
        except VisualAttachmentError as exc:
            raise VisualCapabilityError(
                f"Image attachment rejected: {exc}; the request was rejected "
                "before upstream I/O."
            ) from exc

    if not attachments and url_image_count == 0:
        return None
    return VisualInputReceipt(tuple(attachments), url_image_count)


def validate_visual_capability(
    request: MessagesRequest,
    *,
    model_info: ProviderModelInfo | None,
    model_ref: str,
) -> VisualInputReceipt | None:
    """Reject known-incompatible image input before provider construction/I/O.

    Explicit negative metadata remains fail-closed. Missing or unconfirmed
    metadata is not treated as a negative claim: provider preflight and the
    upstream protocol own the final compatibility decision. Text and tool-only
    requests do not require visual metadata.
    """

    visual_input = validate_visual_input(request)
    required = required_capabilities_for_messages(request)
    if not required.requires(Capability.VISION_INPUT):
        return visual_input
    image_blocks = tuple(_iter_image_blocks(request.messages))
    supports_vision = (
        model_info.effective_supports_vision() if model_info is not None else None
    )
    if supports_vision is False:
        raise VisualCapabilityError(
            f"Model {model_ref!r} does not support image input; the request was "
            "rejected before upstream I/O."
        )

    accepted_types = frozenset(
        model_info.accepted_image_types if model_info is not None else ()
    )
    if not accepted_types:
        return visual_input
    unsupported_types = sorted(
        media_type
        for block in image_blocks
        if (media_type := _base64_media_type(block)) is not None
        and media_type not in accepted_types
    )
    if unsupported_types:
        joined = ", ".join(unsupported_types)
        raise VisualCapabilityError(
            f"Model {model_ref!r} does not accept image type(s): {joined}."
        )
    return visual_input


def _iter_image_blocks(value: object) -> Iterator[object]:
    """Walk message/tool-result content without retaining image bytes."""

    if get_block_type(value) == "image":
        yield value
        return
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _iter_image_blocks(child)
        return
    if isinstance(value, list | tuple):
        for child in value:
            yield from _iter_image_blocks(child)
        return
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        if isinstance(dumped, Mapping):
            yield from _iter_image_blocks(dumped)


def _base64_media_type(block: object) -> str | None:
    source = get_block_attr(block, "source", {})
    if get_block_attr(source, "type") != "base64":
        return None
    media_type = get_block_attr(source, "media_type")
    return media_type if isinstance(media_type, str) else None
