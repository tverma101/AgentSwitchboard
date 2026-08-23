"""OpenAI-chat streamed usage request and extraction helpers."""

import json
from collections.abc import Mapping
from typing import Any

import openai

_USAGE_OPTION_KEYS = ("stream_options", "include_usage")
_USAGE_REJECTION_WORDS = (
    "unsupported",
    "not supported",
    "unknown",
    "unrecognized",
    "unexpected",
    "invalid",
    "extra",
    "forbidden",
    "not permitted",
)


def request_stream_usage(body: dict[str, Any]) -> None:
    """Ask an OpenAI-compatible streaming endpoint for its final usage chunk."""
    stream_options = body.get("stream_options")
    if stream_options is None:
        body["stream_options"] = {"include_usage": True}
        return
    if isinstance(stream_options, dict):
        stream_options["include_usage"] = True


def clone_without_stream_usage(body: dict[str, Any]) -> dict[str, Any] | None:
    """Return a clone with only ``include_usage`` removed from stream options."""
    stream_options = body.get("stream_options")
    if not isinstance(stream_options, dict):
        return None
    if "include_usage" not in stream_options:
        return None

    retry_body = dict(body)
    retry_stream_options = dict(stream_options)
    retry_stream_options.pop("include_usage", None)
    if retry_stream_options:
        retry_body["stream_options"] = retry_stream_options
    else:
        retry_body.pop("stream_options", None)
    return retry_body


def is_stream_usage_rejection(error: Exception) -> bool:
    """Return whether upstream rejected the optional streamed-usage request."""
    if not _is_bad_request_like(error):
        return False
    text = _error_text(error)
    if not any(key in text for key in _USAGE_OPTION_KEYS):
        return False
    return any(word in text for word in _USAGE_REJECTION_WORDS)


def usage_int(usage_info: Any, key: str) -> int | None:
    """Extract an integer usage field from OpenAI SDK objects or plain dicts."""
    value = _usage_value(usage_info, key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def usage_nested_int(usage_info: Any, *keys: str) -> int | None:
    """Extract a nested integer from dicts, SDK models, or model_extra mappings."""
    value = usage_info
    for key in keys:
        value = _usage_value(value, key)
        if value is None:
            return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def cache_usage_fields(usage_info: Any) -> dict[str, int]:
    """Map provider cache counters to disjoint Anthropic usage buckets.

    Anthropic ``input_tokens`` excludes cache reads/writes. OpenAI-compatible
    providers commonly report ``prompt_tokens`` as the total prompt, so passing
    that total through alongside ``cache_read_input_tokens`` double-counts the
    cached prefix. Prefer an explicit cache-miss counter; otherwise subtract a
    nested OpenAI ``prompt_tokens_details.cached_tokens`` value from the total.

    not manufacture ``cache_creation_input_tokens`` from miss counters. When a
    provider reports an explicit write/creation counter, preserve it as the
    corresponding Anthropic cache-creation bucket.
    """

    usage_fields: dict[str, int] = {}
    cache_read = _first_usage_int(
        usage_info, "prompt_cache_hit_tokens", "cache_read_input_tokens"
    )
    if cache_read is None:
        cache_read = _first_nested_usage_int(
            usage_info,
            "prompt_tokens_details",
            "cached_tokens",
        )
    if cache_read is not None:
        usage_fields["cache_read_input_tokens"] = cache_read

    uncached = _first_usage_int(usage_info, "prompt_cache_miss_tokens")
    if uncached is None and cache_read is not None:
        prompt_total = usage_int(usage_info, "prompt_tokens")
        if prompt_total is not None and prompt_total >= cache_read:
            uncached = prompt_total - cache_read
    if uncached is not None:
        # ``AnthropicStreamLedger.message_delta`` merges provider fields last,
        # so this intentionally replaces the OpenAI total prompt count.
        usage_fields["input_tokens"] = uncached

    cache_write = _first_usage_int(
        usage_info,
        "prompt_cache_write_tokens",
        "prompt_cache_creation_tokens",
        "cache_write_tokens",
        "cache_creation_input_tokens",
    )
    if cache_write is None:
        cache_write = _first_nested_usage_int(
            usage_info,
            "prompt_tokens_details",
            "cache_write_tokens",
            "cache_creation_tokens",
            "cache_creation_input_tokens",
        )
    if cache_write is not None:
        usage_fields["cache_creation_input_tokens"] = cache_write
    return usage_fields


def _first_usage_int(usage_info: Any, *keys: str) -> int | None:
    for key in keys:
        value = usage_int(usage_info, key)
        if value is not None:
            return value
    return None


def _first_nested_usage_int(usage_info: Any, parent: str, *keys: str) -> int | None:
    for key in keys:
        value = usage_nested_int(usage_info, parent, key)
        if value is not None:
            return value
    return None

def _usage_value(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(key)
    direct = getattr(value, key, None)
    if direct is not None:
        return direct
    extra = getattr(value, "model_extra", None)
    if isinstance(extra, Mapping):
        return extra.get(key)
    return None


def _is_bad_request_like(error: Exception) -> bool:
    if isinstance(error, openai.BadRequestError):
        return True
    status = getattr(error, "status_code", None)
    if status is None:
        response = getattr(error, "response", None)
        status = (
            getattr(response, "status_code", None) if response is not None else None
        )
    return status in (400, 422)


def _error_text(error: Exception) -> str:
    parts = [str(error)]
    body = getattr(error, "body", None)
    if body is not None:
        parts.append(json.dumps(body, default=str))
    response = getattr(error, "response", None)
    if response is not None:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)
    return " ".join(parts).lower()
