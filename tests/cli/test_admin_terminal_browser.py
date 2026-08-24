"""Tests for terminal-native FCC Admin presentation."""

import subprocess
from unittest.mock import MagicMock, patch

from free_claude_code.cli import commands

ADMIN_URL = "http://127.0.0.1:8080/admin"


def _long_running_process() -> MagicMock:
    process = MagicMock()
    process.wait.side_effect = subprocess.TimeoutExpired(
        cmd="terminal-browser",
        timeout=commands.TERMINAL_BROWSER_STARTUP_PROBE_SECONDS,
    )
    return process


def test_auto_mode_prefers_terminal_browser_in_interactive_terminal() -> None:
    process = _long_running_process()
    with (
        patch.dict(commands.os.environ, {}, clear=True),
        patch.object(commands, "_interactive_terminal_available", return_value=True),
        patch.object(
            commands.shutil,
            "which",
            return_value="/opt/bin/terminal-browser",
        ),
        patch.object(commands.subprocess, "Popen", return_value=process) as popen,
        patch.object(commands.webbrowser, "open") as browser_open,
    ):
        assert commands.open_admin_surface(ADMIN_URL) is True

    popen.assert_called_once_with(
        ["/opt/bin/terminal-browser", "open", ADMIN_URL, "--app-mode"]
    )
    browser_open.assert_not_called()


def test_auto_mode_falls_back_to_system_browser_when_terminal_browser_missing() -> None:
    with (
        patch.dict(commands.os.environ, {}, clear=True),
        patch.object(commands, "_interactive_terminal_available", return_value=True),
        patch.object(commands.shutil, "which", return_value=None),
        patch.object(commands.webbrowser, "open", return_value=True) as browser_open,
    ):
        assert commands.open_admin_surface(ADMIN_URL) is True

    browser_open.assert_called_once_with(ADMIN_URL)


def test_auto_mode_falls_back_when_terminal_browser_exits_with_error() -> None:
    process = MagicMock()
    process.wait.return_value = 2
    with (
        patch.dict(commands.os.environ, {}, clear=True),
        patch.object(commands, "_interactive_terminal_available", return_value=True),
        patch.object(
            commands.shutil,
            "which",
            return_value="/opt/bin/terminal-browser",
        ),
        patch.object(commands.subprocess, "Popen", return_value=process),
        patch.object(commands.webbrowser, "open", return_value=True) as browser_open,
    ):
        assert commands.open_admin_surface(ADMIN_URL) is True

    browser_open.assert_called_once_with(ADMIN_URL)


def test_terminal_mode_never_surprise_opens_system_browser() -> None:
    with (
        patch.dict(
            commands.os.environ,
            {commands.ADMIN_OPEN_MODE_ENV: "terminal"},
            clear=True,
        ),
        patch.object(commands, "_interactive_terminal_available", return_value=False),
        patch.object(commands.shutil, "which", return_value=None),
        patch.object(commands.webbrowser, "open") as browser_open,
    ):
        assert commands.open_admin_surface(ADMIN_URL) is False

    browser_open.assert_not_called()


def test_terminal_mode_does_not_spawn_without_an_interactive_tty() -> None:
    with (
        patch.dict(
            commands.os.environ,
            {commands.ADMIN_OPEN_MODE_ENV: "terminal"},
            clear=True,
        ),
        patch.object(commands, "_interactive_terminal_available", return_value=False),
        patch.object(
            commands.shutil,
            "which",
            return_value="/opt/bin/terminal-browser",
        ) as which,
        patch.object(commands.subprocess, "Popen") as popen,
        patch.object(commands.webbrowser, "open") as browser_open,
    ):
        assert commands.open_admin_surface(ADMIN_URL) is False

    which.assert_not_called()
    popen.assert_not_called()
    browser_open.assert_not_called()


def test_browser_mode_preserves_original_system_browser_behavior() -> None:
    with (
        patch.dict(
            commands.os.environ,
            {commands.ADMIN_OPEN_MODE_ENV: "browser"},
            clear=True,
        ),
        patch.object(commands.shutil, "which") as which,
        patch.object(commands.webbrowser, "open", return_value=True) as browser_open,
    ):
        assert commands.open_admin_surface(ADMIN_URL) is True

    which.assert_not_called()
    browser_open.assert_called_once_with(ADMIN_URL)


def test_auto_mode_uses_browser_for_noninteractive_desktop_launches() -> None:
    with (
        patch.dict(commands.os.environ, {}, clear=True),
        patch.object(commands, "_interactive_terminal_available", return_value=False),
        patch.object(commands.shutil, "which") as which,
        patch.object(commands.webbrowser, "open", return_value=True) as browser_open,
    ):
        assert commands.open_admin_surface(ADMIN_URL) is True

    which.assert_not_called()
    browser_open.assert_called_once_with(ADMIN_URL)


def test_invalid_open_mode_degrades_to_auto() -> None:
    with patch.dict(
        commands.os.environ,
        {commands.ADMIN_OPEN_MODE_ENV: "definitely-not-a-mode"},
        clear=True,
    ):
        assert commands._admin_open_mode() is commands.AdminOpenMode.AUTO


def test_missing_stdio_is_not_treated_as_an_interactive_tty() -> None:
    with (
        patch.object(commands.sys, "stdin", None),
        patch.object(commands.sys, "stdout", None),
    ):
        assert commands._interactive_terminal_available() is False
