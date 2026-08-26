"""Tests for explicit ChatGPT-backed Codex connection from the terminal control center."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        anthropic_auth_token="freecc",
        model="opencode_go/muse-spark-1.2-contributor",
        reasoning_policy=ReasoningPreference.CLIENT,
    )


def _completed(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=args,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_control_menu_connect_is_explicit_and_not_part_of_home_redraw() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    launch = MagicMock()
    with (
        patch("builtins.input", side_effect=["x", "q"]),
        patch.object(terminal_control, "_connect_codex") as connect,
    ):
        terminal_control.run_control_menu(
            settings,
            supervisor=None,
            launch_claude=launch,
        )

    connect.assert_called_once_with()


def test_connect_codex_does_not_launch_login_when_chatgpt_is_already_connected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import terminal_control

    status = _completed(
        ["/usr/local/bin/codex", "login", "status"],
        stdout="Logged in using ChatGPT\n",
    )
    with (
        patch.object(
            terminal_control.shutil, "which", return_value="/usr/local/bin/codex"
        ),
        patch.object(terminal_control.subprocess, "run", return_value=status) as run,
    ):
        terminal_control._connect_codex()

    assert run.call_count == 1
    assert "already connected using ChatGPT" in capsys.readouterr().out


def test_connect_codex_uses_chatgpt_login_and_strips_api_key_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from free_claude_code.cli import terminal_control

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-leak")
    monkeypatch.setenv("FCC_TEST_SENTINEL", "keep-me")

    disconnected = _completed(
        ["/usr/local/bin/codex", "login", "status"],
        returncode=1,
        stderr="Not logged in\n",
    )
    login = _completed(["/usr/local/bin/codex", "login"])
    connected = _completed(
        ["/usr/local/bin/codex", "login", "status"],
        stdout="Logged in using ChatGPT\n",
    )

    with (
        patch.object(
            terminal_control.shutil, "which", return_value="/usr/local/bin/codex"
        ),
        patch.object(
            terminal_control.subprocess,
            "run",
            side_effect=[disconnected, login, connected],
        ) as run,
    ):
        terminal_control._connect_codex()

    assert run.call_count == 3
    for call in run.call_args_list:
        child_env = call.kwargs["env"]
        assert "OPENAI_API_KEY" not in child_env
        assert "CODEX_API_KEY" not in child_env
        assert child_env["FCC_TEST_SENTINEL"] == "keep-me"
    assert run.call_args_list[1].args[0] == ["/usr/local/bin/codex", "login"]
    assert run.call_args_list[1].kwargs["check"] is False


def test_connect_codex_missing_cli_is_local_failure_without_subprocess(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import terminal_control

    with (
        patch.object(terminal_control.shutil, "which", return_value=None),
        patch.object(terminal_control.subprocess, "run") as run,
    ):
        terminal_control._connect_codex()

    run.assert_not_called()
    assert "not found on PATH" in capsys.readouterr().out


def test_codex_subscription_environment_preserves_unrelated_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from free_claude_code.cli.terminal_control import _codex_subscription_environment

    monkeypatch.setenv("OPENAI_API_KEY", "drop")
    monkeypatch.setenv("CODEX_API_KEY", "drop")
    monkeypatch.setenv("FCC_KEEP", "yes")

    environment = _codex_subscription_environment()

    assert "OPENAI_API_KEY" not in environment
    assert "CODEX_API_KEY" not in environment
    assert environment["FCC_KEEP"] == "yes"
    assert os.environ["OPENAI_API_KEY"] == "drop"
