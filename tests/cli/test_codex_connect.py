"""Tests for the explicit Codex tool-account surface in the terminal control center."""

from unittest.mock import MagicMock, patch

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


def test_control_menu_connect_is_explicit_and_not_part_of_home_redraw() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    with (
        patch("builtins.input", side_effect=["x", "q"]),
        patch.object(terminal_control, "_connect_codex") as connect,
    ):
        terminal_control.run_control_menu(
            settings,
            supervisor=None,
            launch_client=MagicMock(),
        )

    connect.assert_called_once_with()


def test_connect_codex_explains_the_separate_surface_without_launching_oauth(
    capsys,
) -> None:
    from free_claude_code.cli import terminal_control

    with patch("free_claude_code.cli.codex_accounts.main") as accounts:
        terminal_control._connect_codex()

    accounts.assert_not_called()
    output = capsys.readouterr().out
    assert "Codex Tool Accounts are separate from the FCC Provider Account." in output
    assert "fcc accounts add <profile>" in output
