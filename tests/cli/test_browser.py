from typing import ClassVar

import pytest

from free_claude_code.cli import browser


class FakeBridge:
    instances: ClassVar[list[FakeBridge]] = []

    def __init__(self, cdp_url: str, *, allow_existing_session: bool) -> None:
        self.cdp_url = cdp_url
        self.allow_existing_session = allow_existing_session
        self.closed = False
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.instances.append(self)

    async def list_tabs(self) -> tuple[dict[str, object], ...]:
        if not self.allow_existing_session:
            raise browser.BrowserCdpError("explicit opt-in")
        self.calls.append(("list_tabs", "", None))
        return ({"tab_id": "tab-1"},)

    async def snapshot_dom(self, tab_id: str) -> dict[str, object]:
        self.calls.append(("snapshot_dom", tab_id, None))
        return {"tab_id": tab_id, "elements": []}

    async def perform(
        self, tab_id: str, action: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        self.calls.append(("perform", f"{tab_id}:{action}", arguments))
        result: dict[str, object] = {"tab_id": tab_id, "action": action}
        if action == "type":
            result["characters"] = len(str(arguments.get("text", "")))
        else:
            result.update(arguments)
        return result

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fake_bridge() -> None:
    FakeBridge.instances.clear()


def test_browser_cli_requires_explicit_existing_session(monkeypatch) -> None:
    monkeypatch.setattr(browser, "ChromeCdpBrowserBridge", FakeBridge)

    with pytest.raises(SystemExit) as exc_info:
        browser.main(["list-tabs"])

    assert exc_info.value.code == 1
    assert FakeBridge.instances[0].allow_existing_session is False
    assert FakeBridge.instances[0].calls == []
    assert FakeBridge.instances[0].closed is True


def test_browser_cli_runs_action_without_echoing_type_payload(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(browser, "ChromeCdpBrowserBridge", FakeBridge)

    browser.main(
        [
            "--cdp-url",
            "http://127.0.0.1:9333",
            "--allow-existing-session",
            "action",
            "tab-1",
            "type",
            "--selector",
            "#name",
            "--text",
            "private-input",
        ]
    )

    output = capsys.readouterr().out
    bridge = FakeBridge.instances[0]
    assert bridge.cdp_url == "http://127.0.0.1:9333"
    assert bridge.allow_existing_session is True
    assert bridge.calls == [
        ("perform", "tab-1:type", {"selector": "#name", "text": "private-input"})
    ]
    assert '"characters": 13' in output
    assert "private-input" not in output
    assert bridge.closed is True


def test_action_arguments_keep_only_command_fields() -> None:
    args = browser._parser().parse_args(
        [
            "--allow-existing-session",
            "action",
            "tab-1",
            "scroll",
            "--delta-y",
            "400",
        ]
    )

    assert browser._action_arguments(args) == {
        "delta_x": 0,
        "delta_y": 400,
    }
