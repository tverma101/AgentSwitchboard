"""Regression tests for first-class provider onboarding in the active TUI."""

from unittest.mock import AsyncMock, patch

import pytest

from free_claude_code.cli.provider_management_tui import (
    ProviderManagementControlCenterApp,
    _provider_test_error_message,
)
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings

CUSTOM_PROVIDER = {
    "provider_id": "acme",
    "display_name": "Acme Gateway",
    "kind": "remote",
    "status": "configured",
    "label": "Configured",
    "custom": True,
    "base_url": "https://api.acme.test/v1",
    "local": False,
    "enabled": True,
    "api_key_configured": True,
    "proxy_configured": False,
    "model_ids": ["acme-small", "acme-large"],
}


def _settings() -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        anthropic_auth_token="freecc",
        model="deepseek/deepseek-chat",
        reasoning_policy=ReasoningPreference.CLIENT,
    )


def test_provider_test_errors_are_actionable() -> None:
    assert "API key" in _provider_test_error_message("AuthenticationError")
    assert "base URL" in _provider_test_error_message("NotFoundError")
    assert "timed out" in _provider_test_error_message("APITimeoutError")
    assert "could not connect" in _provider_test_error_message("APIConnectionError")


def test_failed_provider_test_is_never_reported_as_ok() -> None:
    app = ProviderManagementControlCenterApp(_settings(), supervisor=None)

    with patch.object(app, "notify") as notify:
        app._notify_provider_test(
            "deepseek",
            {"ok": False, "error_type": "AuthenticationError"},
        )

    assert notify.call_count == 1
    message = notify.call_args.args[0]
    assert "authentication rejected" in message
    assert notify.call_args.kwargs["severity"] == "error"


def test_successful_provider_test_reports_discovered_models() -> None:
    app = ProviderManagementControlCenterApp(_settings(), supervisor=None)

    with patch.object(app, "notify") as notify:
        app._notify_provider_test(
            "deepseek",
            {"ok": True, "models": ["deepseek-chat", "deepseek-reasoner"]},
        )

    message = notify.call_args.args[0]
    assert "connected" in message
    assert "2 models discovered" in message
    assert "severity" not in notify.call_args.kwargs


@pytest.mark.asyncio
async def test_custom_provider_gets_real_crud_controls_in_active_tui() -> None:
    config = {"provider_status": [CUSTOM_PROVIDER], "fields": []}
    app = ProviderManagementControlCenterApp(_settings(), supervisor=None)

    with (
        patch(
            "free_claude_code.cli.control_tui.get_admin_config",
            return_value=config,
        ),
        patch(
            "free_claude_code.cli.provider_management_tui.get_admin_config",
            return_value=config,
        ),
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await app._show_page("providers", force=True)
            await pilot.pause()

            assert app.query_one("#custom-provider-add")

            await app._show_provider_detail("acme")
            await pilot.pause()

            assert app.query_one("#custom-provider-edit")
            assert app.query_one("#custom-provider-toggle")
            assert app.query_one("#custom-provider-remove")
            assert app.query_one("#provider-test")


@pytest.mark.asyncio
async def test_builtin_provider_save_immediately_tests_discovery() -> None:
    app = ProviderManagementControlCenterApp(_settings(), supervisor=None)
    show_detail = AsyncMock()

    with (
        patch.object(app, "notify") as notify,
        patch.object(app, "_show_provider_detail", new=show_detail),
        patch.object(app, "_refresh_settings_snapshot"),
        patch(
            "free_claude_code.cli.provider_management_tui.apply_admin_values",
            return_value={"applied": True},
        ),
        patch(
            "free_claude_code.cli.provider_management_tui.test_provider",
            return_value={"ok": True, "models": ["deepseek-chat"]},
        ) as provider_test,
    ):
        await app._apply_field("deepseek", "DEEPSEEK_API_KEY", "secret")

    provider_test.assert_called_once()
    message = notify.call_args.args[0]
    assert "Saved DEEPSEEK_API_KEY" in message
    assert "1 models discovered" in message
    show_detail.assert_awaited_once_with("deepseek")


@pytest.mark.asyncio
async def test_custom_provider_save_retries_across_automatic_restart() -> None:
    app = ProviderManagementControlCenterApp(_settings(), supervisor=None)

    with (
        patch(
            "free_claude_code.cli.provider_management_tui.test_provider",
            side_effect=[
                {"ok": False, "error_type": "UnknownProviderError"},
                {"ok": False, "error_type": "ApplicationUnavailableError"},
                {"ok": True, "models": ["acme-small"]},
            ],
        ) as provider_test,
        patch(
            "free_claude_code.cli.provider_management_tui.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        result = await app._test_provider_until_ready("acme")

    assert result["ok"] is True
    assert provider_test.call_count == 3
