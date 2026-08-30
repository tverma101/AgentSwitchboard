"""Convert Anthropic Messages into an upstream OpenAI Responses request."""

import json
from collections.abc import Mapping
from typing import Any

from free_claude_code.core.anthropic.content import (
    get_block_attr,
    get_block_type,
    is_tool_search_metadata_block,
    is_tool_search_tool_definition,
    is_tool_search_tool_name,
    normalize_image_source,
    without_tool_search_metadata,
)
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.anthropic.openai_tool_names import OpenAIToolNameCodec
from free_claude_code.core.anthropic.request_serialization import (
    serialize_tool_result_content,
    tool_result_media_block_types,
)
from free_claude_code.core.reasoning import ReasoningControl, ReasoningPolicy
from free_claude_code.core.visual_attachments import (
    VisualAttachmentError,
    validate_base64_source,
    validate_image_url,
)

from .cache_identity import select_prompt_cache_key
from .errors import ResponsesConversionError

_REASONING_SUMMARIES = frozenset({"auto", "concise", "detailed"})


def build_responses_provider_request(
    request: MessagesRequest,
    *,
    reasoning: ReasoningPolicy,
    prompt_cache_key: str | None = None,
    explicit_prompt_cache_breakpoint: bool = False,
) -> dict[str, Any]:
    """Build a stateless Responses request without silently dropping fields.

    ``explicit_prompt_cache_breakpoint`` is an opt-in for a caller that has
    verified the target Responses endpoint supports GPT-5.6 cache breakpoints.
    The public ``instructions`` field cannot carry a breakpoint, so the stable
    system prefix is represented as a developer input message when enabled.
    """

    _validate_supported_request(request)
    tool_names = OpenAIToolNameCodec.from_request(request)
    instructions = _system_text(request)
    input_items: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "system":
            text = _message_text(message.content, context="system message")
            if text:
                instructions.append(text)
        elif message.role == "assistant":
            input_items.extend(
                _assistant_items(
                    message.content,
                    reasoning_content=message.reasoning_content,
                    tool_names=tool_names,
                )
            )
        else:
            input_items.extend(_user_items(message.content))

    if not input_items:
        raise ResponsesConversionError(
            "OpenAI Responses conversion requires at least one user or assistant item."
        )

    body: dict[str, Any] = {
        "model": request.model,
        "input": input_items,
        "stream": True,
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    if cache_key := _select_prompt_cache_key(
        explicit=request.prompt_cache_key,
        session=prompt_cache_key or request.claude_session_id,
        metadata=request.metadata,
        content_values=_request_text_values(request),
    ):
        body["prompt_cache_key"] = cache_key
    if instructions:
        instruction_text = "\n\n".join(instructions)
        if explicit_prompt_cache_breakpoint:
            input_items.insert(
                0,
                _developer_message(
                    instruction_text,
                    prompt_cache_breakpoint=True,
                ),
            )
        else:
            body["instructions"] = instruction_text
    if request.max_tokens is not None:
        body["max_output_tokens"] = request.max_tokens
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.top_p is not None:
        body["top_p"] = request.top_p
    if request.metadata is not None:
        body["metadata"] = request.metadata
    if text_config := _responses_text_config(request.output_config):
        body["text"] = text_config
    provider_tools: list[dict[str, Any]] = []
    for tool in request.tools or ():
        if is_tool_search_tool_definition(tool):
            continue
        provider_tools.append(
            {
                "type": "function",
                "name": tool_names.encode(tool.name),
                "description": tool.description,
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
                "strict": False,
            }
        )
    if provider_tools:
        body["tools"] = provider_tools
    if request.tool_choice is not None:
        body["tool_choice"] = _tool_choice(request.tool_choice, tool_names=tool_names)
    if reasoning_config := _reasoning_config(
        reasoning,
        summary=_requested_reasoning_summary(request.output_config),
    ):
        body["reasoning"] = reasoning_config
    return body


def _select_prompt_cache_key(
    *,
    explicit: object,
    session: object,
    metadata: dict[str, Any] | None,
    content_values: list[str],
) -> str | None:
    """Choose a safe metadata-only Responses affinity key."""

    return select_prompt_cache_key(
        explicit=explicit,
        session=session,
        metadata=metadata,
        content_values=content_values,
    )


def _validate_supported_request(request: MessagesRequest) -> None:
    if request.model_extra:
        raise ResponsesConversionError(
            "OpenAI Responses does not support these request fields: "
            f"{sorted(str(key) for key in request.model_extra)}."
        )
    provider_tool_types = sorted(
        {
            tool.type
            for tool in request.tools or ()
            if tool.type is not None and not is_tool_search_tool_definition(tool)
        }
    )
    if provider_tool_types:
        raise ResponsesConversionError(
            "OpenAI Responses cannot represent provider-managed tool types: "
            f"{provider_tool_types}."
        )
    unsupported: list[str] = []
    if request.stop_sequences:
        unsupported.append("stop_sequences")
    if request.top_k is not None:
        unsupported.append("top_k")
    if not _is_noop_context_management(request.context_management):
        unsupported.append("context_management")
    _validate_reasoning_summary(request.output_config)
    _validate_structured_output_format(request.output_config)
    unsupported.extend(_unsupported_output_config_paths(request.output_config))
    if request.mcp_servers:
        unsupported.append("mcp_servers")
    if request.extra_body:
        unsupported.append("extra_body")
    if unsupported:
        raise ResponsesConversionError(
            "OpenAI Responses cannot represent these fields without data loss: "
            f"{unsupported}."
        )


def _unsupported_output_config_paths(
    output_config: dict[str, Any] | None,
) -> list[str]:
    if not output_config:
        return []
    return [
        f"output_config.{key}"
        for key in sorted(output_config)
        if key not in {"effort", "format", "summary"}
    ]


def _validate_reasoning_summary(output_config: dict[str, Any] | None) -> None:
    if not output_config or "summary" not in output_config:
        return
    summary = output_config["summary"]
    if not isinstance(summary, str) or summary not in _REASONING_SUMMARIES:
        raise ResponsesConversionError(
            "output_config.summary must be one of: auto, concise, detailed."
        )


def _validate_structured_output_format(output_config: dict[str, Any] | None) -> None:
    if not output_config or "format" not in output_config:
        return
    value = output_config["format"]
    if not isinstance(value, dict):
        raise ResponsesConversionError("output_config.format must be an object.")
    if set(value) != {"type", "schema"}:
        raise ResponsesConversionError(
            "output_config.format supports exactly type and schema for Responses."
        )
    if value.get("type") != "json_schema":
        raise ResponsesConversionError(
            "output_config.format.type must be 'json_schema' for Responses."
        )
    if not isinstance(value.get("schema"), dict):
        raise ResponsesConversionError(
            "output_config.format.schema must be a JSON Schema object."
        )


def _responses_text_config(
    output_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    _validate_structured_output_format(output_config)
    if not output_config or "format" not in output_config:
        return None
    value = output_config["format"]
    if not isinstance(value, dict):
        return None
    schema = value["schema"]
    return {
        "format": {
            "type": "json_schema",
            "name": "claude_output",
            "schema": schema,
            "strict": True,
        }
    }


def _is_noop_context_management(
    context_management: dict[str, Any] | None,
) -> bool:
    if not context_management:
        return True
    if set(context_management) != {"edits"}:
        return False
    edits = context_management["edits"]
    return isinstance(edits, list) and all(
        isinstance(edit, dict)
        and edit
        == {
            "type": "clear_thinking_20251015",
            "keep": "all",
        }
        for edit in edits
    )


def _system_text(request: MessagesRequest) -> list[str]:
    if request.system is None:
        return []
    if isinstance(request.system, str):
        return [request.system] if request.system else []
    return [part.text for part in request.system if part.text]


def _request_text_values(request: MessagesRequest) -> list[str]:
    """Collect text only to reject cache keys copied from request content."""

    values = _system_text(request)
    for message in request.messages:
        if isinstance(message.content, str):
            values.append(message.content)
        else:
            for block in message.content:
                block_type = get_block_type(block)
                if block_type == "text":
                    text = get_block_attr(block, "text", "")
                    if isinstance(text, str):
                        values.append(text)
                elif block_type == "thinking":
                    thinking = get_block_attr(block, "thinking", "")
                    if isinstance(thinking, str):
                        values.append(thinking)
                elif block_type == "tool_result":
                    content = get_block_attr(block, "content")
                    if isinstance(content, str):
                        values.append(content)
        if message.reasoning_content:
            values.append(message.reasoning_content)
    return values


def _assistant_items(
    content: Any,
    *,
    reasoning_content: str | None,
    tool_names: OpenAIToolNameCodec,
) -> list[dict[str, Any]]:
    if isinstance(content, str):
        items = [_assistant_message([{"type": "output_text", "text": content}])]
        if reasoning_content is not None:
            items.insert(
                0,
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": reasoning_content}],
                },
            )
        return items
    if not isinstance(content, list):
        raise ResponsesConversionError(
            "Assistant content must be text or content blocks."
        )

    items: list[dict[str, Any]] = []
    text_parts: list[dict[str, Any]] = []
    thinking_parts: list[str] = (
        [reasoning_content] if reasoning_content is not None else []
    )
    encrypted_parts: list[str] = []

    def flush_text() -> None:
        if text_parts:
            items.append(_assistant_message(list(text_parts)))
            text_parts.clear()

    for block in content:
        block_type = get_block_type(block)
        if is_tool_search_metadata_block(block):
            continue
        if block_type == "text":
            text_parts.append(
                {
                    "type": "output_text",
                    "text": str(get_block_attr(block, "text", "")),
                }
            )
        elif block_type == "thinking":
            thinking_parts.append(str(get_block_attr(block, "thinking", "")))
        elif block_type == "redacted_thinking":
            encrypted_parts.append(str(get_block_attr(block, "data", "")))
        elif block_type == "tool_use":
            flush_text()
            items.append(
                {
                    "type": "function_call",
                    "call_id": str(get_block_attr(block, "id", "")),
                    "name": tool_names.encode(str(get_block_attr(block, "name", ""))),
                    "arguments": json.dumps(
                        get_block_attr(block, "input", {}),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )
        else:
            raise ResponsesConversionError(
                "OpenAI Responses cannot represent assistant content block "
                f"{block_type!r}."
            )
    if thinking_parts or encrypted_parts:
        summary = [
            {"type": "summary_text", "text": text} for text in thinking_parts if text
        ]
        if encrypted_parts:
            for index, encrypted in enumerate(encrypted_parts):
                item: dict[str, Any] = {
                    "type": "reasoning",
                    "summary": summary if index == 0 else [],
                    "encrypted_content": encrypted,
                }
                items.insert(index, item)
        else:
            items.insert(0, {"type": "reasoning", "summary": summary})
    flush_text()
    return items


def _user_items(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [_user_message([{"type": "input_text", "text": content}])]
    if not isinstance(content, list):
        raise ResponsesConversionError("User content must be text or content blocks.")

    items: list[dict[str, Any]] = []
    message_parts: list[dict[str, Any]] = []

    def flush_message() -> None:
        if message_parts:
            items.append(_user_message(list(message_parts)))
            message_parts.clear()

    for block in content:
        block_type = get_block_type(block)
        if is_tool_search_metadata_block(block):
            continue
        if block_type == "text":
            message_parts.append(
                {
                    "type": "input_text",
                    "text": str(get_block_attr(block, "text", "")),
                }
            )
        elif block_type == "image":
            message_parts.append(_image_part(block))
        elif block_type == "tool_result":
            tool_use_id = str(get_block_attr(block, "tool_use_id", ""))
            tool_content = get_block_attr(block, "content")
            flush_message()
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_use_id,
                    "output": _tool_result_output(
                        tool_content,
                        tool_use_id=tool_use_id,
                    ),
                }
            )
        elif block_type == "document":
            raise ResponsesConversionError(
                "OpenAI Responses provider does not support Anthropic document blocks."
            )
        else:
            raise ResponsesConversionError(
                f"OpenAI Responses cannot represent user content block {block_type!r}."
            )
    flush_message()
    return items


def _tool_result_output(
    content: Any,
    *,
    tool_use_id: str,
) -> str | list[dict[str, Any]]:
    """Convert one Anthropic tool result to a Responses output value.

    Responses function-call outputs support a list of text, image, or file
    input parts. Preserve supported image observations in that native shape so
    Computer Use screenshots reach the model instead of being rejected or
    flattened into text. Unknown nested media remains fail-closed because its
    exact semantics cannot be reconstructed safely.
    """
    content = without_tool_search_metadata(content)
    media_types = tool_result_media_block_types(content)
    if not media_types:
        return serialize_tool_result_content(content)
    if isinstance(content, list):
        blocks = content
    elif isinstance(content, Mapping) and get_block_type(content) in {"text", "image"}:
        # Claude/MCP bridges sometimes emit one content block directly instead
        # of wrapping it in the usual list. It is still losslessly representable
        # by Responses, so normalize that shape before converting it.
        blocks = [content]
    else:
        raise ResponsesConversionError(
            "OpenAI Responses cannot preserve structured media blocks "
            f"{media_types} inside tool_result {tool_use_id!r} unless content is "
            "an Anthropic content-block list; refusing lossy serialization."
        )

    output: list[dict[str, Any]] = []
    for block in blocks:
        block_type = get_block_type(block)
        if is_tool_search_metadata_block(block):
            continue
        if block_type == "text":
            output.append(
                {
                    "type": "input_text",
                    "text": str(get_block_attr(block, "text", "")),
                }
            )
            continue
        if block_type == "image":
            output.append(_image_part(block))
            continue
        if block_type == "document":
            raise ResponsesConversionError(
                "OpenAI Responses cannot represent document blocks inside "
                f"tool_result {tool_use_id!r} without a supported file source; "
                "refusing lossy serialization."
            )
        if tool_result_media_block_types(block):
            raise ResponsesConversionError(
                "OpenAI Responses cannot represent nested structured media blocks "
                f"inside tool_result {tool_use_id!r}; refusing lossy serialization."
            )
        serialized = serialize_tool_result_content(block)
        if serialized:
            output.append({"type": "input_text", "text": serialized})
    return output


def _image_part(block: Any) -> dict[str, Any]:
    source = normalize_image_source(block)
    source_type = get_block_attr(source, "type")
    if source_type == "url":
        url = get_block_attr(source, "url")
        try:
            validate_image_url(url)
        except VisualAttachmentError as exc:
            raise ResponsesConversionError(str(exc)) from exc
    elif source_type == "base64":
        media_type = get_block_attr(source, "media_type")
        data = get_block_attr(source, "data")
        if not isinstance(media_type, str) or not isinstance(data, str):
            raise ResponsesConversionError("Base64 images require media_type and data.")
        try:
            validate_base64_source(source)
        except VisualAttachmentError as exc:
            raise ResponsesConversionError(str(exc)) from exc
        url = f"data:{media_type};base64,{data}"
    else:
        raise ResponsesConversionError(
            f"Unsupported image source type {source_type!r}."
        )
    if not isinstance(url, str) or not url:
        raise ResponsesConversionError("Image source requires a non-empty URL.")
    return {"type": "input_image", "image_url": url}


def _message_text(content: Any, *, context: str) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ResponsesConversionError(f"{context} must contain only text.")
    parts: list[str] = []
    for block in content:
        if get_block_type(block) != "text":
            raise ResponsesConversionError(f"{context} must contain only text.")
        parts.append(str(get_block_attr(block, "text", "")))
    return "\n\n".join(parts)


def _assistant_message(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "message", "role": "assistant", "content": content}


def _user_message(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "message", "role": "user", "content": content}


def _developer_message(
    text: str,
    *,
    prompt_cache_breakpoint: bool,
) -> dict[str, Any]:
    content: dict[str, Any] = {"type": "input_text", "text": text}
    if prompt_cache_breakpoint:
        content["prompt_cache_breakpoint"] = {"mode": "explicit"}
    return {"type": "message", "role": "developer", "content": [content]}


def _tool_choice(
    choice: dict[str, Any],
    *,
    tool_names: OpenAIToolNameCodec,
) -> str | dict[str, str]:
    choice_type = choice.get("type")
    if choice_type in {"auto", "none"}:
        return str(choice_type)
    if choice_type == "any":
        return "required"
    if choice_type == "tool":
        name = choice.get("name")
        if not isinstance(name, str) or not name:
            raise ResponsesConversionError("Forced tool choice requires a tool name.")
        if is_tool_search_tool_name(name):
            return "auto"
        return {"type": "function", "name": tool_names.encode(name)}
    raise ResponsesConversionError(f"Unsupported tool_choice type {choice_type!r}.")


def _requested_reasoning_summary(output_config: dict[str, Any] | None) -> str | None:
    _validate_reasoning_summary(output_config)
    if not output_config:
        return None
    summary = output_config.get("summary")
    return summary if isinstance(summary, str) else None


def _reasoning_config(
    reasoning: ReasoningPolicy,
    *,
    summary: str | None,
) -> dict[str, str]:
    if reasoning.control is ReasoningControl.OFF:
        return {"effort": "none"}
    config = {"summary": summary} if summary is not None else {}
    if reasoning.effort is not None:
        config["effort"] = reasoning.effort.value
        config.setdefault("summary", "auto")
        return config
    if reasoning.requests_reasoning:
        config.setdefault("summary", "auto")
    return config
