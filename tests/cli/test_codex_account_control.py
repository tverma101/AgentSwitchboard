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


def test_control_menu_opens_chatgpt_subscription_accounts_explicitly() -> None:
    from free_claude_code.cli import terminal_control

    with (
        patch("builtins.input", side_effect=["a", "q"]),
        patch("free_claude_code.cli.codex_accounts.main", return_value=0) as accounts,
    ):
        terminal_control.run_control_menu(
            _settings(),
            supervisor=None,
            launch_client=MagicMock(),
        )

    accounts.assert_called_once_with(())
