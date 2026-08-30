"""Hard safety budget for media preserved by context governance."""

import json
from collections.abc import Mapping
from typing import Any

from free_claude_code.core.anthropic.content import get_block_type
from free_claude_code.core.anthropic.models import MessagesRequest, TokenCountRequest

# Preserve screenshots and other protocol media byte-for-byte, but never allow
# preservation to become an unbounded bypass around the context governor. This
# ceiling is intentionally separate from the much smaller text redirect limit.
MAX_PRESERVED_MEDIA_BYTES = 24 * 1024 * 1024
MAX_PRESERVED_MEDIA_ITEMS = 16
_MEDIA_BLOCK_TYPES = frozenset({"audio", "document", "image", "video"})


class PreservedMediaBudgetError(ValueError):
    """Raised when preserved protocol media exceeds the hard request budget."""


def validate_preserved_media_budget(
    request: MessagesRequest | TokenCountRequest,
) -> None:
    """Reject an otherwise-preserved request that exceeds the hard media budget.

    The check is read-only: accepted media is forwarded without rewriting its
    bytes. The budget is aggregate across the request so a burst of individually
    reasonable screenshots cannot bypass the bound by splitting into blocks.
    """

    total_bytes = 0
    total_items = 0
    for message in request.messages:
        for media in _iter_media_blocks(message.content):
            total_items += 1
            if total_items > MAX_PRESERVED_MEDIA_ITEMS:
                raise PreservedMediaBudgetError(
                    "request contains too many preserved media blocks for the context "
                    f"governor ({total_items} > {MAX_PRESERVED_MEDIA_ITEMS})"
                )
            total_bytes += _serialized_media_bytes(media)
            if total_bytes > MAX_PRESERVED_MEDIA_BYTES:
                raise PreservedMediaBudgetError(
                    "preserved media exceeds the context-governor hard request limit "
                    f"({total_bytes} > {MAX_PRESERVED_MEDIA_BYTES} bytes); reduce or "
                    "resize screenshots/media before retrying"
                )


def _iter_media_blocks(value: object):
    if get_block_type(value) in _MEDIA_BLOCK_TYPES:
        yield value
        return
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _iter_media_blocks(child)
        return
    if isinstance(value, list | tuple):
        for child in value:
            yield from _iter_media_blocks(child)
        return
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
        except TypeError, ValueError:
            dumped = model_dump()
        yield from _iter_media_blocks(dumped)


def _serialized_media_bytes(value: object) -> int:
    try:
        encoded = json.dumps(
            value,
            default=_json_default,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except TypeError, ValueError, OverflowError:
        encoded = str(value).encode("utf-8", errors="replace")
    return len(encoded)


def _json_default(value: Any) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return str(value)


__all__ = [
    "MAX_PRESERVED_MEDIA_BYTES",
    "MAX_PRESERVED_MEDIA_ITEMS",
    "PreservedMediaBudgetError",
    "validate_preserved_media_budget",
]
