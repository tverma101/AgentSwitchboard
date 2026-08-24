"""Provider-independent validation for model visual-input capabilities."""

from collections.abc import Iterator, Mapping

from free_claude_code.application.errors import VisualCapabilityError
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.core.anthropic.content import get_block_attr, get_block_type
from free_claude_code.core.anthropic.models import MessagesRequest


def validate_visual_capability(
    request: MessagesRequest,
    *,
    model_info: ProviderModelInfo | None,
    model_ref: str,
) -> None:
    """Reject known-incompatible image input before provider construction/I/O.

    Unknown capability metadata remains permissive so a stale or unavailable
    model catalog cannot break an otherwise valid provider request. A provider
    that explicitly declares no vision support, however, must fail closed.
    """

    image_blocks = tuple(_iter_image_blocks(request.messages))
    if not image_blocks or model_info is None:
        return
    if model_info.supports_vision is False:
        raise VisualCapabilityError(
            f"Model {model_ref!r} does not support image input; "
            "the request was rejected before upstream I/O."
        )

    accepted_types = frozenset(model_info.accepted_image_types)
    if not accepted_types:
        return
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
