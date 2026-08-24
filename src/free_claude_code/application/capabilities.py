"""Provider-independent request capability extraction."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

from free_claude_code.core.anthropic.content import get_block_attr, get_block_type
from free_claude_code.core.anthropic.models import MessagesRequest


class Capability(StrEnum):
    """Capabilities that can affect request routing or validation."""

    TEXT_INPUT = "text_input"
    TEXT_OUTPUT = "text_output"
    NATIVE_TOOLS = "native_tools"
    PARALLEL_TOOLS = "parallel_tools"
    NAMED_TOOL_CHOICE = "named_tool_choice"
    REASONING_EFFORT = "reasoning_effort"
    STRUCTURED_OUTPUT = "structured_output"
    VISION_INPUT = "vision_input"
    IMAGE_TOOL_RESULTS = "image_tool_results"
    SCREENSHOT_VISION = "screenshot_vision"
    SEMANTIC_BROWSER_CONTROL = "semantic_browser_control"
    SEMANTIC_MACOS_CONTROL = "semantic_macos_control"
    PIXEL_COMPUTER_USE = "pixel_computer_use"


@dataclass(frozen=True, slots=True)
class RequiredCapabilitySet:
    """Deterministic capabilities required by one incoming request."""

    capabilities: frozenset[Capability]
    reasons: tuple[tuple[str, str], ...] = ()

    def requires(self, capability: Capability) -> bool:
        """Return whether the request requires ``capability``."""

        return capability in self.capabilities

    def as_dict(self) -> dict[str, object]:
        """Return a metadata-only representation suitable for receipts."""

        return {
            "capabilities": sorted(
                capability.value for capability in self.capabilities
            ),
            "reasons": [
                {"capability": capability, "reason": reason}
                for capability, reason in self.reasons
            ],
        }


def required_capabilities_for_messages(
    request: MessagesRequest,
) -> RequiredCapabilitySet:
    """Derive required capabilities without inspecting prompt or image bytes."""

    capabilities = {Capability.TEXT_INPUT, Capability.TEXT_OUTPUT}
    reasons: list[tuple[str, str]] = []

    def require(capability: Capability, reason: str) -> None:
        capabilities.add(capability)
        reasons.append((capability.value, reason))

    if request.tools:
        require(Capability.NATIVE_TOOLS, "request declares tools")
        tool_names = tuple(tool.name.casefold() for tool in request.tools)
        if any(_looks_like_browser_tool(name) for name in tool_names):
            require(Capability.SEMANTIC_BROWSER_CONTROL, "browser/CDP tool declared")
        if any(_looks_like_macos_tool(name) for name in tool_names):
            require(Capability.SEMANTIC_MACOS_CONTROL, "macOS/AX tool declared")
        if any(_looks_like_screenshot_tool(name) for name in tool_names):
            require(Capability.SCREENSHOT_VISION, "screenshot tool declared")

    if _is_named_tool_choice(request.tool_choice):
        require(Capability.NAMED_TOOL_CHOICE, "forced or named tool choice")

    if request.thinking is not None and request.thinking.enabled is not False:
        require(Capability.REASONING_EFFORT, "thinking configuration declared")

    if _has_structured_output(request.output_config):
        require(
            Capability.STRUCTURED_OUTPUT,
            "structured output configuration declared",
        )

    if (request.model_extra or {}).get("parallel_tool_calls") is True:
        require(Capability.PARALLEL_TOOLS, "parallel_tool_calls enabled")

    for message in request.messages:
        tool_use_count = 0
        for block, inside_tool_result in _iter_blocks(message.content):
            block_type = get_block_type(block)
            if block_type == "image":
                require(Capability.VISION_INPUT, "image content block")
                if inside_tool_result:
                    require(
                        Capability.IMAGE_TOOL_RESULTS,
                        "image nested in tool_result",
                    )
            elif block_type == "tool_use":
                tool_use_count += 1
                tool_name = get_block_attr(block, "name")
                if isinstance(tool_name, str):
                    normalized_name = tool_name.casefold()
                    if _looks_like_browser_tool(normalized_name):
                        require(
                            Capability.SEMANTIC_BROWSER_CONTROL,
                            "browser/CDP tool use",
                        )
                    if _looks_like_macos_tool(normalized_name):
                        require(
                            Capability.SEMANTIC_MACOS_CONTROL,
                            "macOS/AX tool use",
                        )
                    if _looks_like_screenshot_tool(normalized_name):
                        require(
                            Capability.SCREENSHOT_VISION,
                            "screenshot tool use",
                        )
        if tool_use_count > 1:
            require(Capability.PARALLEL_TOOLS, "multiple tool_use blocks in one turn")

    return RequiredCapabilitySet(
        capabilities=frozenset(capabilities),
        reasons=tuple(sorted(set(reasons))),
    )


def _iter_blocks(
    value: object,
    *,
    inside_tool_result: bool = False,
) -> Iterator[tuple[object, bool]]:
    block_type = get_block_type(value)
    if block_type is not None:
        yield value, inside_tool_result
        if block_type == "tool_result":
            yield from _iter_blocks(
                get_block_attr(value, "content"), inside_tool_result=True
            )
        return
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _iter_blocks(child, inside_tool_result=inside_tool_result)
        return
    if isinstance(value, list | tuple):
        for child in value:
            yield from _iter_blocks(child, inside_tool_result=inside_tool_result)
        return
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        if isinstance(dumped, Mapping):
            yield from _iter_blocks(dumped, inside_tool_result=inside_tool_result)


def _is_named_tool_choice(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    return bool(
        value.get("name")
        or value.get("type") == "tool"
        or isinstance(value.get("function"), Mapping)
    )


def _has_structured_output(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    return any(key in value for key in ("format", "json_schema", "schema"))


def _looks_like_browser_tool(name: str) -> bool:
    return any(token in name for token in ("browser", "cdp", "dom"))


def _looks_like_macos_tool(name: str) -> bool:
    return any(token in name for token in ("computer", "macos", "accessibility", "ax_"))


def _looks_like_screenshot_tool(name: str) -> bool:
    return "screenshot" in name or "screen_capture" in name


__all__ = ["Capability", "RequiredCapabilitySet", "required_capabilities_for_messages"]
