"""Reasoning and thinking conversion helpers for OpenAI Responses."""

from collections.abc import Mapping
from typing import Any

from .tools import optional_str


def reasoning_text_from_item(item: Mapping[str, Any]) -> str | None:
    """Return both raw reasoning and its provider-written summary.

    Responses reasoning items may carry the two representations at the same
    time. Preferring ``content`` silently discarded the summary on the next
    request, while preferring ``summary`` discarded raw text. Keep both in a
    deterministic order; identical representations are emitted once.
    """
    content_parts = _text_parts_from_items(
        item.get("content"), item_type="reasoning_text"
    )
    summary_parts = _text_parts_from_items(
        item.get("summary"), item_type="summary_text"
    )
    content = "\n".join(content_parts) if content_parts else None
    summary = "\n".join(summary_parts) if summary_parts else None
    if content is not None and summary is not None and content == summary:
        return content
    return combine_reasoning(content, summary)


def encrypted_reasoning_from_item(item: Mapping[str, Any]) -> str | None:
    """Return opaque reasoning content without interpreting it."""

    return optional_str(item.get("encrypted_content"))


def combine_reasoning(existing: str | None, addition: str | None) -> str | None:
    if addition is None:
        return existing
    if existing is None:
        return addition
    if existing == "":
        return addition
    if addition == "":
        return existing
    return f"{existing}\n{addition}"


def responses_reasoning_to_output_config(value: Any) -> dict[str, Any] | None:
    """Preserve the client's effort and summary controls for resolution."""
    if not isinstance(value, Mapping):
        return None
    output_config: dict[str, Any] = {}
    effort = value.get("effort")
    if isinstance(effort, str) and effort.strip():
        output_config["effort"] = effort.strip().lower()
    if "summary" in value:
        summary = value["summary"]
        output_config["summary"] = (
            summary.strip().lower() if isinstance(summary, str) else summary
        )
    return output_config or None


def _text_parts_from_items(value: Any, *, item_type: str) -> list[str]:
    if not isinstance(value, list):
        return []
    parts: list[str] = []
    for item in value:
        if isinstance(item, dict) and item.get("type") == item_type:
            text = optional_str(item.get("text"))
            if text is not None:
                parts.append(text)
    return parts
