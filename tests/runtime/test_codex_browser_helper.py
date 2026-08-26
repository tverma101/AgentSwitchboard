import io
import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from free_claude_code.application.capabilities import Capability
from free_claude_code.runtime.codex_browser_helper import (
    BROWSER_OPERATIONS,
    CODEX_BROWSER_HELPER_ID,
    MUTATING_BROWSER_OPERATIONS,
    READ_ONLY_BROWSER_OPERATIONS,
    CodexBrowserHelperAdapter,
    CodexBrowserHelperError,
)


class _FakeProcess:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(json.dumps(response) + "\n")
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_browser_helper_metadata_is_local_bounded_and_controller_preserving() -> None:
    adapter = CodexBrowserHelperAdapter()

    helper = adapter.approved_helper()

    assert helper.helper_id == CODEX_BROWSER_HELPER_ID
    assert helper.local is True
    assert helper.billable is False
    assert helper.capabilities == frozenset(
        {Capability.SEMANTIC_BROWSER_CONTROL, Capability.SCREENSHOT_VISION}
    )
    assert helper.mutating_operations == MUTATING_BROWSER_OPERATIONS
    assert READ_ONLY_BROWSER_OPERATIONS.isdisjoint(MUTATING_BROWSER_OPERATIONS)
    assert READ_ONLY_BROWSER_OPERATIONS | MUTATING_BROWSER_OPERATIONS == BROWSER_OPERATIONS


def test_browser_helper_rejects_unknown_operation_before_startup() -> None:
    adapter = CodexBrowserHelperAdapter()

    with patch("free_claude_code.runtime.codex_browser_helper.subprocess.Popen") as popen:
        with pytest.raises(CodexBrowserHelperError, match="unsupported"):
            adapter.execute("evaluate_javascript", {}, threading.Event())

    popen.assert_not_called()


def test_browser_helper_rejects_cancelled_call_before_startup() -> None:
    adapter = CodexBrowserHelperAdapter()
    cancelled = threading.Event()
    cancelled.set()

    with patch("free_claude_code.runtime.codex_browser_helper.subprocess.Popen") as popen:
        with pytest.raises(CodexBrowserHelperError, match="cancelled before dispatch"):
            adapter.execute("list_tabs", {}, cancelled)

    popen.assert_not_called()


def test_browser_helper_uses_one_warm_json_line_process() -> None:
    adapter = CodexBrowserHelperAdapter(session_id="test-session")
    fake = _FakeProcess(
        {
            "id": 1,
            "ok": True,
            "result": {"family": "chrome", "tabs": [{"id": "tab-1"}]},
        }
    )
    captured: dict[str, object] = {}

    def fake_popen(*args: object, **kwargs: object) -> _FakeProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake

    with (
        patch(
            "free_claude_code.runtime.codex_browser_helper.shutil.which",
            return_value="/usr/bin/node",
        ),
        patch(
            "free_claude_code.runtime.codex_browser_helper.subprocess.Popen",
            side_effect=fake_popen,
        ) as popen,
    ):
        result = adapter.execute("list_tabs", {}, threading.Event())

    assert result == {"family": "chrome", "tabs": [{"id": "tab-1"}]}
    popen.assert_called_once()
    request = json.loads(fake.stdin.getvalue())
    assert request == {"id": 1, "operation": "list_tabs", "arguments": {}}
    raw_args = captured["args"]
    assert isinstance(raw_args, tuple)
    command = raw_args[0]
    assert isinstance(command, list)
    assert command[0] == "/usr/bin/node"
    assert Path(command[1]).name == "codex_browser_helper.mjs"


def test_browser_helper_child_environment_does_not_forward_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    monkeypatch.setenv("CODEX_HOME", "/tmp/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai")
    monkeypatch.setenv("CODEX_API_KEY", "secret-codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-anthropic")
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-router")
    adapter = CodexBrowserHelperAdapter(
        family="edge",
        plugin_root=Path("/tmp/plugin"),
        session_id="session-42",
    )

    environment = adapter._child_environment()

    assert environment["PATH"] == "/usr/bin"
    assert environment["HOME"] == "/tmp/home"
    assert environment["CODEX_HOME"] == "/tmp/codex"
    assert environment["FCC_CODEX_BROWSER_FAMILY"] == "edge"
    assert environment["FCC_CODEX_BROWSER_PLUGIN_ROOT"] == "/tmp/plugin"
    assert environment["FCC_CODEX_BROWSER_SESSION_ID"] == "session-42"
    assert "OPENAI_API_KEY" not in environment
    assert "CODEX_API_KEY" not in environment
    assert "ANTHROPIC_API_KEY" not in environment
    assert "OPENROUTER_API_KEY" not in environment


def test_browser_helper_requires_node_only_when_first_used() -> None:
    adapter = CodexBrowserHelperAdapter()

    with patch(
        "free_claude_code.runtime.codex_browser_helper.shutil.which",
        return_value=None,
    ):
        with pytest.raises(CodexBrowserHelperError, match="Node.js is required"):
            adapter.execute("list_tabs", {}, threading.Event())


def test_browser_helper_configuration_is_operator_owned() -> None:
    with pytest.raises(ValueError, match="family"):
        CodexBrowserHelperAdapter(family="safari")
    with pytest.raises(ValueError, match="absolute"):
        CodexBrowserHelperAdapter(plugin_root=Path("relative/plugin"))
