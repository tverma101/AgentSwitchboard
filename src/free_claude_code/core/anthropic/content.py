"""Content block helpers for Anthropic-compatible payloads."""

from collections.abc import Mapping
from typing import Any


def get_block_attr(block: Any, attr: str, default: Any = None) -> Any:
    """Get an attribute from a Pydantic model, lightweight object, or dict."""
    if hasattr(block, attr):
        return getattr(block, attr)
    if isinstance(block, Mapping):
        return block.get(attr, default)
    return default


def get_block_type(block: Any) -> str | None:
    """Return a content block type when present."""
    return get_block_attr(block, "type")


_TOOL_SEARCH_METADATA_BLOCK_TYPES = frozenset(
    {
        "tool_reference",
        "tool_search_tool_result",
        "tool_search_tool_search_result",
        "tool_search_tool_result_error",
    }
)
_TOOL_SEARCH_TOOL_NAME_PREFIX = "tool_search_tool_"


def is_tool_search_metadata_block(block: Any) -> bool:
    """Return whether a block is Claude's search-only control metadata.

    These blocks are meaningful to Claude Code's Anthropic endpoint, but are
    not ordinary MCP observations. FCC routes the actual named MCP tools to
    OpenAI-compatible providers, so serializing these control blocks as JSON
    would either waste context or make a provider reject the request.
    """
    block_type = get_block_type(block)
    if block_type in _TOOL_SEARCH_METADATA_BLOCK_TYPES:
        return True
    return block_type == "server_tool_use" and _is_tool_search_controller_name(
        get_block_attr(block, "name")
    )


def is_tool_search_tool_name(name: Any) -> bool:
    """Return whether a tool name belongs to Anthropic's search controller."""
    return isinstance(name, str) and name.startswith(_TOOL_SEARCH_TOOL_NAME_PREFIX)


def _is_tool_search_controller_name(name: Any) -> bool:
    return isinstance(name, str) and (
        name == "tool_search" or name.startswith(_TOOL_SEARCH_TOOL_NAME_PREFIX)
    )


def is_tool_search_tool_definition(tool: Any) -> bool:
    """Return whether a tool definition is server-managed search machinery."""
    tool_type = get_block_type(tool)
    return (
        isinstance(tool_type, str)
        and tool_type.startswith(_TOOL_SEARCH_TOOL_NAME_PREFIX)
    ) or is_tool_search_tool_name(get_block_attr(tool, "name"))


def without_tool_search_metadata(content: Any) -> Any:
    """Remove search-control blocks while preserving all real tool content."""
    normalized = normalize_tool_result_content(content)
    if is_tool_search_metadata_block(normalized):
        return None
    if isinstance(normalized, list):
        return [
            block for block in normalized if not is_tool_search_metadata_block(block)
        ]
    return normalized


_MCP_TOOL_RESULT_FIELDS = frozenset(
    {"content", "isError", "is_error", "_meta", "structuredContent"}
)
_MCP_JSONRPC_RESULT_FIELDS = frozenset({"jsonrpc", "id", "result"})


def normalize_tool_result_content(content: Any) -> Any:
    """Unwrap a complete MCP result while preserving its content blocks.

    Claude history normally stores the MCP ``content`` array directly inside
    an Anthropic ``tool_result`` block.  Some MCP adapters instead pass the
    complete ``CallToolResult`` (or JSON-RPC ``result`` envelope) through that
    field.  Treating that envelope as model content causes image blocks to be
    mistaken for unsupported nested media and leaks protocol metadata into
    text-only providers.  Only the exact MCP envelope shapes are unwrapped;
    arbitrary application dictionaries remain untouched.
    """

    normalized = _normalized_tool_result_content(content)
    return content if normalized is None else normalized


def _normalized_tool_result_content(content: Any) -> Any | None:
    mapping = _content_mapping(content)
    if mapping is None:
        return None

    # A real content block is already normalized.  In particular, an image
    # block may legitimately contain a field named ``content`` in a provider
    # extension, so never treat typed blocks as envelopes.
    if "type" in mapping:
        return None

    keys = set(mapping)
    nested_content = mapping.get("content")
    if (
        "content" in keys
        and keys <= _MCP_TOOL_RESULT_FIELDS
        and isinstance(nested_content, list)
    ):
        return nested_content

    if keys <= _MCP_JSONRPC_RESULT_FIELDS and "result" in mapping:
        return _normalized_tool_result_content(mapping["result"])

    return None


def _content_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if not callable(model_dump):
        return None
    try:
        dumped = model_dump(mode="python")
    except TypeError, ValueError:
        try:
            dumped = model_dump()
        except TypeError, ValueError:
            return None
    return dumped if isinstance(dumped, Mapping) else None


def normalize_image_source(block: Any) -> dict[str, Any]:
    """Return an Anthropic-shaped image source for every supported wire shape.

    Anthropic messages use ``image.source`` with snake-case fields, while MCP
    tool results commonly use the compact shape ``{type: "image", data,
    mimeType}``.  Keeping this normalization at the protocol boundary lets
    every OpenAI adapter preserve the original image bytes without teaching
    each adapter about MCP's camel-case spelling.
    """

    source = get_block_attr(block, "source")
    if isinstance(source, Mapping):
        normalized = dict(source)
        if "media_type" not in normalized:
            for alias in ("mimeType", "mime_type"):
                if alias in normalized:
                    normalized["media_type"] = normalized[alias]
                    break
        return normalized

    if source is not None:
        source_type = get_block_attr(source, "type")
        if source_type is not None:
            normalized = {"type": source_type}
            for field in ("url", "data", "media_type", "mimeType", "mime_type"):
                value = get_block_attr(source, field)
                if value is not None:
                    normalized[field] = value
            if "media_type" not in normalized:
                for alias in ("mimeType", "mime_type"):
                    if alias in normalized:
                        normalized["media_type"] = normalized[alias]
                        break
            return normalized

    if get_block_type(block) == "image":
        data = get_block_attr(block, "data")
        media_type = get_block_attr(block, "mimeType")
        if media_type is None:
            media_type = get_block_attr(block, "mime_type")
        return {
            "type": "base64",
            "media_type": media_type,
            "data": data,
        }

    return {}


def extract_text_from_content(content: Any) -> str:
    """Extract concatenated text from message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            text = get_block_attr(block, "text", "")
            if isinstance(text, str) and text:
                parts.append(text)
        return "".join(parts)
    return ""
