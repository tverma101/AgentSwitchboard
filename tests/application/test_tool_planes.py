from collections.abc import Mapping, Sequence

import pytest

from free_claude_code.application.tool_planes import (
    LocalToolError,
    LocalToolPlane,
    local_tool_names,
)
from free_claude_code.core.provider_policy import ProviderEgressGuard, ProviderPolicy


class FakeComputer:
    async def screenshot(self, *, window_id: str | None = None) -> bytes:
        return f"shot:{window_id}".encode()

    async def inspect_window(self, window_id: str) -> Mapping[str, object]:
        return {"window_id": window_id, "app": "FakeApp"}

    async def perform(
        self, action: str, arguments: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {"action": action, "arguments": dict(arguments)}


class FakeBrowser:
    async def list_tabs(self) -> Sequence[Mapping[str, object]]:
        return ({"tab_id": "tab-1"},)

    async def snapshot_dom(self, tab_id: str) -> Mapping[str, object]:
        return {"tab_id": tab_id, "text": "ready"}

    async def perform(
        self, tab_id: str, action: str, arguments: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {"tab_id": tab_id, "action": action, "arguments": dict(arguments)}


def test_local_tool_names_are_stable_and_provider_independent() -> None:
    assert local_tool_names() == (
        "computer.screenshot",
        "computer.inspect_window",
        "computer.perform",
        "browser.list_tabs",
        "browser.snapshot_dom",
        "browser.perform",
    )


@pytest.mark.asyncio
async def test_dispatches_local_computer_and_browser_tools_with_receipts() -> None:
    guard = ProviderEgressGuard(ProviderPolicy("opencode_go", "model"))
    plane = LocalToolPlane(FakeComputer(), FakeBrowser(), guard)

    assert (
        await plane.invoke("computer.screenshot", {"window_id": "w-1"}) == b"shot:w-1"
    )
    assert await plane.invoke("computer.perform", {"action": "click"}) == {
        "action": "click",
        "arguments": {},
    }
    assert await plane.invoke("browser.list_tabs") == ({"tab_id": "tab-1"},)
    assert await plane.invoke(
        "browser.perform",
        {"tab_id": "tab-1", "action": "click", "arguments": {"selector": "#go"}},
    ) == {
        "tab_id": "tab-1",
        "action": "click",
        "arguments": {"selector": "#go"},
    }
    assert guard.receipt()["counts"] == {"local": 4}


@pytest.mark.asyncio
async def test_missing_plane_and_bad_arguments_fail_closed() -> None:
    plane = LocalToolPlane()

    with pytest.raises(LocalToolError, match="unavailable"):
        await plane.invoke("computer.screenshot")
    with pytest.raises(LocalToolError, match="window_id"):
        await LocalToolPlane(FakeComputer()).invoke("computer.inspect_window")
    with pytest.raises(LocalToolError, match="unknown local tool"):
        await plane.invoke("browser.download")
