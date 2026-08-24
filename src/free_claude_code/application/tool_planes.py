"""Provider-independent local computer and browser tool-plane contracts."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from free_claude_code.core.provider_policy import ProviderEgressGuard


class LocalToolError(RuntimeError):
    """A local tool is unavailable or rejected by its safety policy."""


class ComputerUsePort(Protocol):
    """Small local-only contract for an OS computer-use adapter."""

    async def screenshot(self, *, window_id: str | None = None) -> bytes: ...

    async def inspect_window(self, window_id: str) -> Mapping[str, object]: ...

    async def perform(
        self, action: str, arguments: Mapping[str, object]
    ) -> Mapping[str, object]: ...


class BrowserBridgePort(Protocol):
    """Small local-only contract for a CDP/DOM adapter."""

    async def list_tabs(self) -> Sequence[Mapping[str, object]]: ...

    async def snapshot_dom(self, tab_id: str) -> Mapping[str, object]: ...

    async def perform(
        self, tab_id: str, action: str, arguments: Mapping[str, object]
    ) -> Mapping[str, object]: ...


@dataclass(slots=True)
class LocalToolPlane:
    """Dispatch the small stable tool surface without selecting a model provider.

    Concrete macOS Accessibility and browser-CDP adapters are injected by the
    application boundary. The dispatcher deliberately has no credential or
    network client of its own; every call is accounted as local before the
    adapter is invoked.
    """

    computer: ComputerUsePort | None = None
    browser: BrowserBridgePort | None = None
    egress_guard: ProviderEgressGuard | None = None

    async def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, object] | None = None,
        *,
        session_id: str | None = None,
    ) -> Mapping[str, object] | Sequence[Mapping[str, object]] | bytes:
        """Invoke one provider-independent local tool by its stable name."""

        args = arguments or {}
        if self.egress_guard is not None:
            allowed = self.egress_guard.authorize(
                "local",
                model=tool_name,
                category="local_tool",
                session_id=session_id,
            )
            if not allowed:
                raise LocalToolError(
                    "local tool egress blocked before network I/O by diagnostic policy"
                )

        if tool_name == "computer.screenshot":
            if self.computer is None:
                raise LocalToolError("computer tool plane is unavailable")
            return await self.computer.screenshot(
                window_id=_optional_string(args, "window_id")
            )
        if tool_name == "computer.inspect_window":
            if self.computer is None:
                raise LocalToolError("computer tool plane is unavailable")
            return await self.computer.inspect_window(
                _required_string(args, "window_id")
            )
        if tool_name == "computer.perform":
            if self.computer is None:
                raise LocalToolError("computer tool plane is unavailable")
            return await self.computer.perform(
                _required_string(args, "action"),
                _mapping(args.get("arguments")),
            )
        if tool_name == "browser.list_tabs":
            if self.browser is None:
                raise LocalToolError("browser tool plane is unavailable")
            return await self.browser.list_tabs()
        if tool_name == "browser.snapshot_dom":
            if self.browser is None:
                raise LocalToolError("browser tool plane is unavailable")
            return await self.browser.snapshot_dom(_required_string(args, "tab_id"))
        if tool_name == "browser.perform":
            if self.browser is None:
                raise LocalToolError("browser tool plane is unavailable")
            return await self.browser.perform(
                _required_string(args, "tab_id"),
                _required_string(args, "action"),
                _mapping(args.get("arguments")),
            )
        raise LocalToolError(f"unknown local tool: {tool_name}")


def local_tool_names() -> tuple[str, ...]:
    """Return deterministic tool names for a stable prompt/tool schema."""

    return (
        "computer.screenshot",
        "computer.inspect_window",
        "computer.perform",
        "browser.list_tabs",
        "browser.snapshot_dom",
        "browser.perform",
    )


def _required_string(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise LocalToolError(f"local tool argument {name!r} must be a non-empty string")
    return value


def _optional_string(arguments: Mapping[str, object], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise LocalToolError(f"local tool argument {name!r} must be a string")
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise LocalToolError("local tool arguments must be an object")
    return {str(key): item for key, item in value.items()}
