"""Behavior tests for the Harlequin-derived CodeSwitchyard control center.

The ``App.run_test()`` / Pilot pattern is adapted from Harlequin's functional
TUI tests at commit fcfaa6c524a6cd47e17701d931eac0243c8c85b6.
"""

from unittest.mock import patch

import pytest
from textual.widgets import DataTable, OptionList

from free_claude_code.application.connected_accounts import ConnectedAccountLoginMode
from free_claude_code.cli.control_tui import ControlCenterApp
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


@pytest.mark.asyncio
async def test_control_tui_mounts_persistent_navigation_shell() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="fcc@example.com",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="codex@example.com (profile personal)",
        ),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            nav = app.query_one("#nav", OptionList)
            assert nav.option_count >= 10
            assert app.query_one("#main-panel")
            assert app.query_one("#actions")
            assert app.query_one("#launch-claude")
            assert app.query_one("#launch-danger")


@pytest.mark.asyncio
async def test_provider_table_overlays_live_connected_account_state() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    config = {
        "provider_status": [
            {
                "provider_id": "openai",
                "display_name": "OpenAI / ChatGPT",
                "kind": "connected_account",
                "status": "disconnected",
                "label": "Not connected",
            }
        ],
        "fields": [],
    }
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.get_admin_config",
            return_value=config,
        ),
        patch(
            "free_claude_code.cli.control_tui.connected_account_status",
            return_value={
                "state": "connected",
                "connected": True,
                "email": "fcc@example.com",
                "model_count": 6,
            },
        ),
    ):
        async with app.run_test() as pilot:
            await app._show_page("providers")
            await pilot.pause()
            table = app.query_one("#table", DataTable)
            row = table.get_row("openai")
            assert row[0] == "OpenAI / ChatGPT"
            assert "Connected" in str(row[1])
            assert "fcc@example.com" in str(row[1])


@pytest.mark.asyncio
async def test_browser_login_waits_for_real_connected_state() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    config = {
        "provider_status": [
            {
                "provider_id": "openai",
                "display_name": "OpenAI / ChatGPT",
                "kind": "connected_account",
                "status": "disconnected",
                "label": "Not connected",
            }
        ],
        "fields": [],
    }
    statuses = iter(
        [
            {
                "state": "connecting",
                "connected": False,
                "model_count": 0,
            },
            {
                "state": "connected",
                "connected": True,
                "email": "fcc@example.com",
                "model_count": 6,
            },
        ]
    )

    def status(*_args: object, **_kwargs: object) -> dict[str, object]:
        try:
            return next(statuses)
        except StopIteration:
            return {
                "state": "connected",
                "connected": True,
                "email": "fcc@example.com",
                "model_count": 6,
            }

    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.get_admin_config",
            return_value=config,
        ),
        patch(
            "free_claude_code.cli.control_tui.start_connected_account_login",
            return_value={
                "state": "connecting",
                "authorization_url": "https://example.test/login",
            },
        ),
        patch(
            "free_claude_code.cli.control_tui.connected_account_status",
            side_effect=status,
        ),
        patch("free_claude_code.cli.control_tui.webbrowser.open") as browser_open,
    ):
        async with app.run_test() as pilot:
            app.selected_provider = "openai"
            await app._start_fcc_login(ConnectedAccountLoginMode.BROWSER)
            await pilot.pause()
            browser_open.assert_called_once_with("https://example.test/login")
            assert app._oauth_provider == "openai"
            await app._poll_live_state()
            await pilot.pause()
            assert app._oauth_provider is None


@pytest.mark.asyncio
async def test_repo_navigation_never_uses_nested_input_prompts() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.load_cached_repos",
            return_value=[],
        ),
        patch("builtins.input", side_effect=AssertionError("TUI must not call input()")),
    ):
        async with app.run_test() as pilot:
            await app._show_page("repos")
            await pilot.pause()
            table = app.query_one("#table", DataTable)
            assert table.row_count == 0
            assert app.query_one("#repo-refresh")
