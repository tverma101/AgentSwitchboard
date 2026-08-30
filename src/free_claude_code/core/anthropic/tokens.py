"""Token estimation for Anthropic-compatible requests."""

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable, Mapping
from threading import BoundedSemaphore, Condition
from typing import cast

import tiktoken
from loguru import logger
from pydantic import BaseModel

from .content import (
    get_block_attr,
    is_tool_search_metadata_block,
    is_tool_search_tool_definition,
    normalize_image_source,
    without_tool_search_metadata,
)
from .models import Message, SystemContent, Tool

ENCODER = tiktoken.get_encoding("cl100k_base")

_DISALLOWED_SPECIAL: tuple[str, ...] = ()
_TOKEN_COUNT_CACHE_MAX_ENTRIES = 128
_TOKEN_COUNT_CACHE_MAX_KEY_BYTES = 4 * 1024 * 1024
_TOKEN_COUNT_CACHE_REVISION = "anthropic-token-estimate-v2"
_TOKEN_COUNT_MAX_CONCURRENT_COMPUTATIONS = 2
_TOKEN_COUNT_WORK_LIMIT = BoundedSemaphore(_TOKEN_COUNT_MAX_CONCURRENT_COMPUTATIONS)
_CACHE_UNSUPPORTED = object()
_MEDIA_BLOCK_TYPES = frozenset({"audio", "document", "image", "video"})


def _count_text_tokens(text: str) -> int:
    return len(ENCODER.encode(text, disallowed_special=_DISALLOWED_SPECIAL))


class _TokenCountMemo:
    """Bounded, thread-safe memoization for repeated client count probes.

    Claude Code can issue a burst of identical count requests while it is
    rendering context or deciding whether to compact.  The in-flight set
    makes those requests share one calculation instead of rescanning the
    complete transcript concurrently.  Only a digest and a small integer are
    retained; request content is never stored in the cache.
    """

    def __init__(self, max_entries: int, *, max_concurrent: int) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self._max_entries = max_entries
        self._max_concurrent = max_concurrent
        self._condition = Condition()
        self._values: OrderedDict[str, int] = OrderedDict()
        self._in_flight: set[str] = set()
        self._active_computations = 0

    def get_or_compute(self, key: str, compute: Callable[[], int]) -> int:
        with self._condition:
            while True:
                if key in self._values:
                    value = self._values[key]
                    self._values.move_to_end(key)
                    return value
                if (
                    key not in self._in_flight
                    and self._active_computations < self._max_concurrent
                ):
                    self._in_flight.add(key)
                    self._active_computations += 1
                    break
                self._condition.wait()

        try:
            value = compute()
        except BaseException:
            with self._condition:
                self._in_flight.discard(key)
                self._active_computations -= 1
                self._condition.notify_all()
            raise

        with self._condition:
            self._values[key] = value
            self._values.move_to_end(key)
            while len(self._values) > self._max_entries:
                self._values.popitem(last=False)
            self._in_flight.discard(key)
            self._active_computations -= 1
            self._condition.notify_all()
        return value

    def clear(self) -> None:
        """Clear completed entries without interrupting active calculations."""
        with self._condition:
            self._values.clear()


_TOKEN_COUNT_MEMO = _TokenCountMemo(
    _TOKEN_COUNT_CACHE_MAX_ENTRIES,
    max_concurrent=_TOKEN_COUNT_MAX_CONCURRENT_COMPUTATIONS,
)


def get_token_count(
    messages: list[Message],
    system: str | list[SystemContent] | None = None,
    tools: list[Tool] | None = None,
) -> int:
    """Estimate tokens with stable reuse and bounded total probe work.

    The work limit covers both request fingerprinting and tokenization. Large
    Computer Use screenshots must not be serialized or hashed concurrently by
    every burst of client-side context probes before memoization can help.
    """
    with _TOKEN_COUNT_WORK_LIMIT:
        ordinary_tools = tuple(
            tool for tool in tools or () if not is_tool_search_tool_definition(tool)
        )
        cache_key = _token_count_cache_key(messages, system, ordinary_tools)
        if cache_key is None:
            return _count_token_request(messages, system, ordinary_tools)
        return _TOKEN_COUNT_MEMO.get_or_compute(
            cache_key,
            lambda: _count_token_request(messages, system, ordinary_tools),
        )


def _count_token_request(
    messages: list[Message],
    system: str | list[SystemContent] | None,
    tools: tuple[Tool, ...],
) -> int:
    """Perform one uncached token estimate."""
    total_tokens = 0

    if system:
        if isinstance(system, str):
            total_tokens += _count_text_tokens(system)
        elif isinstance(system, list):
            for block in system:
                text = get_block_attr(block, "text", "")
                if text:
                    total_tokens += _count_text_tokens(str(text))
        total_tokens += 4

    for msg in messages:
        if isinstance(msg.content, str):
            total_tokens += _count_text_tokens(msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                b_type = get_block_attr(block, "type") or None

                if is_tool_search_metadata_block(block):
                    continue

                if b_type == "text":
                    text = get_block_attr(block, "text", "")
                    total_tokens += _count_text_tokens(str(text))
                elif b_type == "thinking":
                    thinking = get_block_attr(block, "thinking", "")
                    total_tokens += _count_text_tokens(str(thinking))
                elif b_type == "tool_use":
                    name = get_block_attr(block, "name", "")
                    inp = get_block_attr(block, "input", {})
                    block_id = get_block_attr(block, "id", "")
                    total_tokens += _count_text_tokens(str(name))
                    total_tokens += _count_text_tokens(_json_text_for_count(inp))
                    total_tokens += _count_text_tokens(str(block_id))
                    total_tokens += 15
                elif b_type == "image":
                    total_tokens += _count_media_block(block)
                elif b_type == "tool_result":
                    content = without_tool_search_metadata(
                        get_block_attr(block, "content", "")
                    )
                    tool_use_id = get_block_attr(block, "tool_use_id", "")
                    total_tokens += _count_tool_result_content(content)
                    total_tokens += _count_text_tokens(str(tool_use_id))
                    total_tokens += 8
                elif b_type in (
                    "server_tool_use",
                    "web_search_tool_result",
                    "web_fetch_tool_result",
                ):
                    if hasattr(block, "model_dump"):
                        blob: object = block.model_dump()
                    else:
                        blob = block
                    try:
                        total_tokens += _count_text_tokens(_json_text_for_count(blob))
                    except (TypeError, ValueError, OverflowError) as e:
                        logger.debug(
                            "Block encode fallback b_type={} err={}", b_type, e
                        )
                        total_tokens += _count_text_tokens(str(blob))
                    total_tokens += 12
                else:
                    logger.debug(
                        "Unexpected block type %r, falling back to json/str encoding",
                        b_type,
                    )
                    total_tokens += _count_json_tokens(block)

    if tools:
        for tool in tools:
            tool_str = (
                tool.name
                + (tool.description or "")
                + _json_text_for_count(tool.input_schema)
            )
            total_tokens += _count_text_tokens(tool_str)

    total_tokens += len(messages) * 4
    if tools:
        total_tokens += len(tools) * 5

    return max(1, total_tokens)


def _count_tool_result_content(content: object) -> int:
    """Count tool output semantically without tokenizing media encodings."""
    if isinstance(content, str):
        return _count_text_tokens(content)
    if isinstance(content, list):
        return sum(_count_content_value(block) for block in content)
    return _count_content_value(content)


def _count_content_value(value: object) -> int:
    """Count one content value while treating structured media as media."""
    block_type = get_block_attr(value, "type")
    if is_tool_search_metadata_block(value):
        return 0
    if block_type == "text":
        return _count_text_tokens(str(get_block_attr(value, "text", "")))
    if isinstance(block_type, str) and block_type in _MEDIA_BLOCK_TYPES:
        return _count_media_block(value)
    if block_type == "tool_result":
        return _count_tool_result_content(get_block_attr(value, "content", ""))
    if isinstance(value, list):
        return sum(_count_content_value(item) for item in value)
    return _count_json_tokens(value)


def _count_media_block(block: object) -> int:
    """Estimate structured media without counting its base64 representation."""
    source = normalize_image_source(block)
    data = source.get("data") or source.get("base64") or ""
    if isinstance(data, str) and data:
        return max(85, len(data) // 3000)
    return 765


def _count_json_tokens(value: object) -> int:
    return _count_text_tokens(_json_text_for_count(value))


def _json_text_for_count(value: object) -> str:
    """Serialize JSON deterministically for stable token estimates."""
    try:
        return json.dumps(
            value,
            default=_json_default,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        logger.debug("Structured token-count fallback err={}", exc)
        return str(value)


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


def _token_count_cache_key(
    messages: list[Message],
    system: str | list[SystemContent] | None,
    tools: tuple[Tool, ...],
) -> str | None:
    """Build a bounded, content-free cache key for one token-count input."""
    canonical = _canonical_value(
        {
            "revision": _TOKEN_COUNT_CACHE_REVISION,
            "messages": messages,
            "system": system,
            "tools": tools,
        }
    )
    if canonical is _CACHE_UNSUPPORTED:
        return None
    try:
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except TypeError, ValueError, OverflowError:
        return None
    if len(encoded) > _TOKEN_COUNT_CACHE_MAX_KEY_BYTES:
        return None
    return hashlib.sha256(encoded).hexdigest()


def _canonical_value(value: object) -> object:
    """Convert supported protocol values into deterministic JSON data."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        block_type = value.get("type")
        if isinstance(block_type, str) and (
            block_type in _MEDIA_BLOCK_TYPES or block_type == "base64"
        ):
            return _canonical_media_mapping(cast(Mapping[object, object], value))
        result: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                return _CACHE_UNSUPPORTED
            normalized = _canonical_value(nested)
            if normalized is _CACHE_UNSUPPORTED:
                return _CACHE_UNSUPPORTED
            result[key] = normalized
        return result
    if isinstance(value, list | tuple):
        result = []
        for nested in value:
            normalized = _canonical_value(nested)
            if normalized is _CACHE_UNSUPPORTED:
                return _CACHE_UNSUPPORTED
            result.append(normalized)
        return result

    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="json"))
    return _CACHE_UNSUPPORTED


def _canonical_media_mapping(value: Mapping[object, object]) -> object:
    """Replace media payloads with bounded digests in cache keys only."""
    result: dict[str, object] = {}
    for key, nested in value.items():
        if not isinstance(key, str):
            return _CACHE_UNSUPPORTED
        if key in {"data", "base64"} and isinstance(nested, str):
            encoded = nested.encode("utf-8")
            result[key] = {
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "length": len(encoded),
            }
            continue
        normalized = _canonical_value(nested)
        if normalized is _CACHE_UNSUPPORTED:
            return _CACHE_UNSUPPORTED
        result[key] = normalized
    return result
