"""Provider-independent request capability extraction."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

from free_claude_code.application.errors import InvalidRequestError
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


class CapabilityRoutingMode(StrEnum):
    """Explicit policies for resolving unsupported controller capabilities."""

    STRICT = "strict"
    SMART_LOCAL = "smart_local"
    SMART_GO = "smart_go"
    CUSTOM = "custom"


class CapabilityRoutingError(InvalidRequestError):
    """A required capability cannot be served under the active policy."""


@dataclass(frozen=True, slots=True)
class CapabilityHelper:
    """An explicitly configured subordinate capability route."""

    helper_id: str
    provider_family: str
    model_ref: str
    capabilities: frozenset[Capability]
    local: bool = False
    billable: bool = False


@dataclass(frozen=True, slots=True)
class CapabilityRoutingPolicy:
    """Allowlisted helper policy; controller failover is never implicit."""

    mode: CapabilityRoutingMode = CapabilityRoutingMode.STRICT
    allowed_helpers: frozenset[str] = frozenset()
    allow_controller_failover: bool = False

    def __post_init__(self) -> None:
        if self.mode is CapabilityRoutingMode.STRICT and (
            self.allowed_helpers or self.allow_controller_failover
        ):
            raise ValueError(
                "strict capability routing cannot permit helpers or failover"
            )


@dataclass(frozen=True, slots=True)
class CapabilityRoutePlan:
    """A controller-preserving capability decision and its receipt data."""

    controller_provider: str
    controller_model: str
    required: RequiredCapabilitySet
    mode: CapabilityRoutingMode
    decision: str
    unknown: frozenset[Capability] = frozenset()
    unsupported: frozenset[Capability] = frozenset()
    helpers: tuple[CapabilityHelper, ...] = ()
    controller_failover: bool = False

    def as_receipt(self) -> dict[str, object]:
        """Return metadata without request content or image bytes."""

        return {
            "controller_provider": self.controller_provider,
            "controller_model": self.controller_model,
            "required": self.required.as_dict(),
            "mode": self.mode.value,
            "decision": self.decision,
            "unknown": sorted(capability.value for capability in self.unknown),
            "unsupported": sorted(capability.value for capability in self.unsupported),
            "controller_failover": self.controller_failover,
            "helpers": [
                {
                    "helper_id": helper.helper_id,
                    "provider_family": helper.provider_family,
                    "model_ref": helper.model_ref,
                    "capabilities": sorted(
                        capability.value for capability in helper.capabilities
                    ),
                    "local": helper.local,
                    "billable": helper.billable,
                }
                for helper in self.helpers
            ],
        }


class CapabilityRouter:
    """Plan capability helpers without replacing the primary controller."""

    def __init__(self, policy: CapabilityRoutingPolicy | None = None) -> None:
        self._policy = policy or CapabilityRoutingPolicy()

    def plan(
        self,
        required: RequiredCapabilitySet,
        *,
        controller_provider: str,
        controller_model: str,
        supported_capabilities: frozenset[Capability] = frozenset(),
        known_capabilities: frozenset[Capability] = frozenset(),
        helpers: tuple[CapabilityHelper, ...] = (),
    ) -> CapabilityRoutePlan:
        """Return a strict controller or an explicit helper chain."""

        baseline = {Capability.TEXT_INPUT, Capability.TEXT_OUTPUT}
        requested = set(required.capabilities) - baseline
        supported = set(supported_capabilities)
        known = set(known_capabilities)
        unknown = frozenset(requested - known)
        unsupported = frozenset((requested & known) - supported)
        missing = unknown | unsupported
        if not missing:
            return CapabilityRoutePlan(
                controller_provider=controller_provider,
                controller_model=controller_model,
                required=required,
                mode=self._policy.mode,
                decision="primary",
            )

        selected, remaining = self._select_helpers(missing, helpers)
        if remaining:
            names = ", ".join(sorted(capability.value for capability in remaining))
            if self._policy.allow_controller_failover:
                raise CapabilityRoutingError(
                    "controller failover is a separate policy and cannot be "
                    f"performed automatically for: {names}"
                )
            raise CapabilityRoutingError(
                f"required capabilities are unavailable under "
                f"{self._policy.mode.value} policy: {names}"
            )
        return CapabilityRoutePlan(
            controller_provider=controller_provider,
            controller_model=controller_model,
            required=required,
            mode=self._policy.mode,
            decision="helpers",
            unknown=unknown,
            unsupported=unsupported,
            helpers=tuple(selected),
        )

    def _select_helpers(
        self,
        missing: frozenset[Capability],
        helpers: tuple[CapabilityHelper, ...],
    ) -> tuple[list[CapabilityHelper], set[Capability]]:
        remaining = set(missing)
        selected: list[CapabilityHelper] = []
        for helper in helpers:
            if not self._helper_allowed(helper):
                continue
            covered = remaining & set(helper.capabilities)
            if not covered:
                continue
            selected.append(helper)
            remaining -= covered
            if not remaining:
                break
        return selected, remaining

    def _helper_allowed(self, helper: CapabilityHelper) -> bool:
        if helper.helper_id not in self._policy.allowed_helpers:
            return False
        if self._policy.mode is CapabilityRoutingMode.STRICT:
            return False
        if self._policy.mode is CapabilityRoutingMode.SMART_LOCAL:
            return helper.local
        if self._policy.mode is CapabilityRoutingMode.SMART_GO:
            return helper.provider_family.casefold() == "opencode_go"
        return True


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


__all__ = [
    "Capability",
    "CapabilityHelper",
    "CapabilityRoutePlan",
    "CapabilityRouter",
    "CapabilityRoutingError",
    "CapabilityRoutingMode",
    "CapabilityRoutingPolicy",
    "RequiredCapabilitySet",
    "required_capabilities_for_messages",
]
