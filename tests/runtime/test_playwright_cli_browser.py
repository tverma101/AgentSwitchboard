"""Tests for the bounded Microsoft Playwright CLI browser adapter."""

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from free_claude_code.application.capabilities import Capability
from free_claude_code.runtime.playwright_cli_browser import (
    MUTATING_PLAYWRIGHT_OPERATIONS,
    PLAYWRIGHT_CLI_HELPER_ID,
    READ_ONLY_PLAYWRIGHT_OPERATIONS,
    PlaywrightAttachMode,
    PlaywrightCliBrowserAdapter,
    PlaywrightCliBrowserError,
    PlaywrightCliOperation,
    resolve_playwright_cli,
)


class _FakeProcess:
    def __init__(self, stdout: str, *, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def communicate(self, *, timeout: float) -> tuple[str, str]:
        return self.stdout, self.stderr

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def _executable(tmp_path: Path) -> Path:
    executable = tmp_path / "playwright-cli"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    return executable


def test_approved_helper_declares_local_browser_capability_and_side_effects(
    tmp_path: Path,
) -> None:
    helper = PlaywrightCliBrowserAdapter(
        executable=_executable(tmp_path)
    ).approved_helper()

    assert helper.helper_id == PLAYWRIGHT_CLI_HELPER_ID
    assert helper.provider_family == "browser"
    assert helper.capabilities == frozenset({Capability.SEMANTIC_BROWSER_CONTROL})
    assert helper.local is True
    assert helper.billable is False
    assert helper.mutating_operations == MUTATING_PLAYWRIGHT_OPERATIONS
    assert READ_ONLY_PLAYWRIGHT_OPERATIONS.isdisjoint(helper.mutating_operations)
    assert PlaywrightCliOperation.SCREENSHOT.value in helper.mutating_operations
    assert PlaywrightCliOperation.DOWNLOAD.value in helper.mutating_operations


def test_command_mapping_matches_official_cli_surface(tmp_path: Path) -> None:
    adapter = PlaywrightCliBrowserAdapter(
        executable=_executable(tmp_path),
        session_name="unit-test",
        headed=True,
    )

    assert adapter._command(PlaywrightCliOperation.STATUS, {}) == ["list"]
    assert adapter._command(PlaywrightCliOperation.LIST_TABS, {}) == ["tab-list"]
    assert adapter._command(
        PlaywrightCliOperation.OPEN,
        {"url": "https://example.test/start"},
    ) == ["open", "https://example.test/start", "--headed"]
    assert adapter._command(
        PlaywrightCliOperation.GOTO,
        {"url": "https://example.test/next"},
    ) == ["goto", "https://example.test/next"]
    assert adapter._command(
        PlaywrightCliOperation.SNAPSHOT,
        {"target": "e1", "depth": 3},
    ) == ["snapshot", "e1", "--depth=3"]
    assert adapter._command(
        PlaywrightCliOperation.FIND,
        {"text": "Submit", "regex": True},
    ) == ["find", "--regex", "Submit"]
    assert adapter._command(
        PlaywrightCliOperation.CLICK,
        {"target": "e2", "button": "right"},
    ) == ["click", "e2", "right"]
    assert adapter._command(
        PlaywrightCliOperation.FILL,
        {"target": "e3", "text": "hello", "submit": True},
    ) == ["fill", "e3", "hello", "--submit"]
    assert adapter._command(
        PlaywrightCliOperation.TYPE_TEXT,
        {"text": "literal"},
    ) == ["type", "literal"]
    assert adapter._command(
        PlaywrightCliOperation.PRESS_KEY,
        {"key": "Enter"},
    ) == ["press", "Enter"]
    assert adapter._command(
        PlaywrightCliOperation.SCROLL,
        {"delta_x": 0, "delta_y": 100},
    ) == ["mousewheel", "0.0", "100.0"]
    assert adapter._command(
        PlaywrightCliOperation.CONSOLE,
        {"min_level": "warning"},
    ) == ["console", "warning"]
    assert adapter._command(
        PlaywrightCliOperation.SCREENSHOT,
        {"target": "e4", "hires": True},
    ) == ["screenshot", "e4", "--hires"]
    assert adapter._command(
        PlaywrightCliOperation.DOWNLOAD,
        {"request_index": 4},
    ) == ["response-body", "4"]
    assert adapter._command(PlaywrightCliOperation.CLOSE, {}) == ["close"]


def test_status_invocation_uses_json_session_and_hides_profile_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _executable(tmp_path)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    payload = {
        "browsers": [
            {
                "name": "unit-test",
                "status": "open",
                "browserType": "chrome",
                "headed": False,
                "persistent": False,
                "attached": False,
                "compatible": True,
                "version": "0.1.18",
                "workspace": "/private/secret/workspace",
                "userDataDir": "/private/secret/profile",
            }
        ]
    }

    def fake_popen(argv: list[str], **kwargs: Any) -> _FakeProcess:
        calls.append((argv, kwargs))
        return _FakeProcess(json.dumps(payload))

    monkeypatch.setattr(
        "free_claude_code.runtime.playwright_cli_browser.subprocess.Popen",
        fake_popen,
    )
    adapter = PlaywrightCliBrowserAdapter(
        executable=executable,
        session_name="unit-test",
    )

    result = adapter.execute("status", {}, threading.Event())

    assert result == {
        "browsers": [
            {
                "name": "unit-test",
                "status": "open",
                "browserType": "chrome",
                "headed": False,
                "persistent": False,
                "attached": False,
                "compatible": True,
                "version": "0.1.18",
            }
        ]
    }
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [str(executable), "--json", "-s=unit-test", "list"]
    assert kwargs["shell"] is False
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["env"]["NO_UPDATE_NOTIFIER"] == "1"
    assert "/private/secret" not in json.dumps(result)


def test_tab_inventory_strips_url_credentials_query_and_fragment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _executable(tmp_path)

    def fake_popen(argv: list[str], **kwargs: Any) -> _FakeProcess:
        return _FakeProcess(
            json.dumps(
                {
                    "result": "- 0: [account](https://user:pass@example.test/path?token=secret#fragment)"
                }
            )
        )

    monkeypatch.setattr(
        "free_claude_code.runtime.playwright_cli_browser.subprocess.Popen",
        fake_popen,
    )
    adapter = PlaywrightCliBrowserAdapter(executable=executable)

    result = adapter.execute("list_tabs", {}, threading.Event())

    assert result == {"result": "- 0: [account](https://example.test/path)"}
    assert "secret" not in json.dumps(result)
    assert "user:pass" not in json.dumps(result)


def test_explicit_attachment_is_required_and_runs_attach_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _executable(tmp_path)
    calls: list[list[str]] = []
    outputs = iter(({}, {"result": "- 0: [page](https://example.test/)"}))

    def fake_popen(argv: list[str], **kwargs: Any) -> _FakeProcess:
        calls.append(argv)
        return _FakeProcess(json.dumps(next(outputs)))

    monkeypatch.setattr(
        "free_claude_code.runtime.playwright_cli_browser.subprocess.Popen",
        fake_popen,
    )

    with pytest.raises(ValueError, match="explicit opt-in"):
        PlaywrightCliBrowserAdapter(
            executable=executable,
            attach_mode=PlaywrightAttachMode.CDP,
            attach_target="http://127.0.0.1:9222",
        )

    adapter = PlaywrightCliBrowserAdapter(
        executable=executable,
        session_name="attached",
        allow_existing_session=True,
        attach_mode=PlaywrightAttachMode.CDP,
        attach_target="http://127.0.0.1:9222",
    )
    result = adapter.execute("list_tabs", {}, threading.Event())

    assert result == {"result": "- 0: [page](https://example.test/)"}
    assert calls == [
        [
            str(executable),
            "--json",
            "-s=attached",
            "attach",
            "--cdp=http://127.0.0.1:9222",
        ],
        [str(executable), "--json", "-s=attached", "tab-list"],
    ]


def test_invalid_navigation_and_attachment_targets_are_rejected(tmp_path: Path) -> None:
    executable = _executable(tmp_path)
    adapter = PlaywrightCliBrowserAdapter(executable=executable)

    with pytest.raises(PlaywrightCliBrowserError, match="credentials"):
        adapter._command(
            PlaywrightCliOperation.GOTO,
            {"url": "https://user:pass@example.test/"},
        )
    with pytest.raises(PlaywrightCliBrowserError, match="invalid port"):
        adapter._command(
            PlaywrightCliOperation.GOTO,
            {"url": "https://example.test:not-a-port/"},
        )
    with pytest.raises(ValueError, match="loopback"):
        PlaywrightCliBrowserAdapter(
            executable=executable,
            allow_existing_session=True,
            attach_mode=PlaywrightAttachMode.CDP,
            attach_target="http://example.test:9222",
        )
    with pytest.raises(ValueError, match="credentials"):
        PlaywrightCliBrowserAdapter(
            executable=executable,
            allow_existing_session=True,
            attach_mode=PlaywrightAttachMode.CDP,
            attach_target="http://user:pass@127.0.0.1:9222",
        )
    with pytest.raises(PlaywrightCliBrowserError, match="between 1 and 100000"):
        adapter._command(PlaywrightCliOperation.DOWNLOAD, {"request_index": 0})


def test_cancellation_is_rejected_before_executable_resolution(tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    adapter = PlaywrightCliBrowserAdapter(executable=tmp_path / "missing")

    with pytest.raises(PlaywrightCliBrowserError, match="cancelled before dispatch"):
        adapter.execute("snapshot", {}, cancel)


def test_cli_failure_preserves_upstream_error_without_shell_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _executable(tmp_path)
    calls: list[dict[str, Any]] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> _FakeProcess:
        calls.append(kwargs)
        return _FakeProcess(
            json.dumps({"isError": True, "error": "browser is not open"}),
            returncode=1,
        )

    monkeypatch.setattr(
        "free_claude_code.runtime.playwright_cli_browser.subprocess.Popen",
        fake_popen,
    )

    with pytest.raises(PlaywrightCliBrowserError, match="browser is not open"):
        PlaywrightCliBrowserAdapter(executable=executable).execute(
            "snapshot",
            {},
            threading.Event(),
        )
    assert calls[0]["shell"] is False


def test_resolver_never_falls_back_to_npx_or_install(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "free_claude_code.runtime.playwright_cli_browser.shutil.which",
        lambda name: None,
    )

    with pytest.raises(PlaywrightCliBrowserError, match="not installed"):
        resolve_playwright_cli()
