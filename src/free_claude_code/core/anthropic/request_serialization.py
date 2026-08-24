"""Shared Anthropic request serialization helpers."""

import json
from typing import Any

from .models import MessagesRequest

_MESSAGES_REQUEST_FIELDS = (
    "model",
    "messages",
    "system",
    "max_tokens",
    "stop_sequences",
    "stream",
    "temperature",
    "top_p",
    "top_k",
    "metadata",
    "tools",
    "tool_choice",
    "thinking",
    "context_management",
    "output_config",
    "mcp_servers",
    "extra_body",
)

_TOOL_RESULT_MEDIA_BLOCK_TYPES = frozenset({"image", "document"})


def dump_messages_request(request: MessagesRequest) -> dict[str, Any]:
    """Return JSON-ready public Messages fields without FCC routing state."""
    raw = request.model_dump(exclude_none=True)
    return {
        field: raw[field]
        for field in _MESSAGES_REQUEST_FIELDS
        if field in raw and raw[field] is not None
    }


def serialize_tool_result_content(content: Any) -> str:
    """Serialize Anthropic ``tool_result.content`` into provider-safe text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict):
                parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def tool_result_media_block_types(content: Any) -> tuple[str, ...]:
    """Return structured media block types nested in tool-result content.

    OpenAI-compatible tool output fields are not uniformly multimodal. Callers
    must inspect this before converting structured content to text so an image
    or document cannot disappear behind a successful-looking JSON request.
    """
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            block_type = value.get("type")
            if block_type in _TOOL_RESULT_MEDIA_BLOCK_TYPES:
                found.add(block_type)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(content)
    return tuple(sorted(found))
