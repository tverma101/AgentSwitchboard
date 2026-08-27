import json
import subprocess

import pytest

from free_claude_code.cli import macos_screenshot


def test_screen_recording_permission_is_requested_once_without_terminal_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        requested = command[-1] == "--request"
        payload = {"requested": requested, "screenCapture": False}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    macos_screenshot._request_screen_recording_once.cache_clear()
    monkeypatch.setattr(macos_screenshot.subprocess, "run", fake_run)

    for _ in range(2):
        with pytest.raises(
            macos_screenshot.MacOSScreenRecordingPermissionError,
            match="Screen Recording permission is required for Terminal",
        ):
            macos_screenshot.ensure_screen_recording_permission(
                {"TERM_PROGRAM": "Apple_Terminal"}
            )

    permission_commands = [
        command
        for command in commands
        if command[-1].endswith("macos_permissions.swift") or command[-1] == "--request"
    ]
    request_commands = [command for command in commands if command[-1] == "--request"]
    assert len(permission_commands) == 5
    assert len(request_commands) == 1
    assert capsys.readouterr() == ("", "")


def test_screen_recording_permission_does_not_request_when_already_granted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        payload = {"requested": False, "screenCapture": True}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    macos_screenshot._request_screen_recording_once.cache_clear()
    monkeypatch.setattr(macos_screenshot.subprocess, "run", fake_run)

    macos_screenshot.ensure_screen_recording_permission(
        {"TERM_PROGRAM": "Apple_Terminal"}
    )

    assert len(commands) == 1
    assert "--request" not in commands[0]


def test_focused_window_metadata_uses_one_bundled_swift_window_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        payload = {
            "selected": {
                "id": 7312,
                "owner": "Safari",
                "name": "localhost:3000",
                "bundle_id": "com.apple.Safari",
                "bounds": {"x": 12, "y": 34, "width": 800, "height": 600},
            }
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(macos_screenshot.subprocess, "run", fake_run)

    metadata = macos_screenshot.focused_window_metadata()

    assert metadata == {
        "app": "Safari",
        "window": "localhost:3000",
        "bundle_id": "com.apple.Safari",
        "x": 12,
        "y": 34,
        "width": 800,
        "height": 600,
        "window_id": 7312,
    }
    assert len(commands) == 1
    assert commands[0][0] == "swift"
    assert commands[0][-1].endswith("macos_focused_window.swift")
    assert "osascript" not in commands[0]


def test_focused_window_metadata_fails_closed_without_a_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, '{"selected":null}', "")

    monkeypatch.setattr(macos_screenshot.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="no focused macOS window"):
        macos_screenshot.focused_window_metadata()
