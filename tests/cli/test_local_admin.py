"""Tests for the loopback terminal client of FCC's canonical Admin API."""

from unittest.mock import call, patch

import pytest

from free_claude_code.application.connected_accounts import ConnectedAccountLoginMode
from free_claude_code.cli import local_admin
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    return Settings.model_construct(host="0.0.0.0", port=8082)


def test_apply_admin_values_validates_before_apply() -> None:
    settings = _settings()
    values = {"MODEL": "opencode_go/muse-spark-1.2-contributor"}
    with patch.object(
        local_admin,
        "_request_json",
        side_effect=[{"valid": True}, {"applied": True, "valid": True}],
    ) as request:
        result = local_admin.apply_admin_values(settings, values)

    assert result["applied"] is True
    assert request.call_args_list == [
        call(
            settings,
            "/admin/api/config/validate",
            method="POST",
            payload={"values": values},
        ),
        call(
            settings,
            "/admin/api/config/apply",
            method="POST",
            payload={"values": values},
        ),
    ]


def test_apply_admin_values_never_applies_invalid_preview() -> None:
    settings = _settings()
    validation = {"valid": False, "errors": ["bad model"]}
    with patch.object(
        local_admin,
        "_request_json",
        return_value=validation,
    ) as request:
        result = local_admin.apply_admin_values(settings, {"MODEL": "bad"})

    assert result == validation | {"applied": False}
    request.assert_called_once_with(
        settings,
        "/admin/api/config/validate",
        method="POST",
        payload={"values": {"MODEL": "bad"}},
    )


def test_terminal_read_actions_use_canonical_admin_routes() -> None:
    settings = _settings()
    with patch.object(local_admin, "_request_json", return_value={}) as request:
        local_admin.get_admin_status(settings)
        local_admin.get_models(settings)
        local_admin.get_usage(settings, days=7)
        local_admin.get_local_provider_status(settings)
        local_admin.test_provider(settings, "openai/codex")
        local_admin.route_diagnostic(settings, model="muse", shapes=("text",))

    assert request.call_args_list == [
        call(settings, "/admin/api/status"),
        call(settings, "/admin/api/models", method="GET"),
        call(settings, "/admin/api/usage?days=7"),
        call(settings, "/admin/api/providers/local-status"),
        call(
            settings,
            "/admin/api/providers/openai%2Fcodex/test",
            method="POST",
        ),
        call(
            settings,
            "/admin/api/diagnostics/route",
            method="POST",
            payload={"shapes": ("text",), "mode": "strict", "model": "muse"},
        ),
    ]


def test_connected_account_actions_are_secret_free_and_use_expected_methods() -> None:
    settings = _settings()
    with patch.object(local_admin, "_request_json", return_value={}) as request:
        local_admin.connected_account_status(settings, "openai")
        local_admin.start_connected_account_login(
            settings, "openai", ConnectedAccountLoginMode.DEVICE
        )
        local_admin.cancel_connected_account_login(settings, "openai")
        local_admin.disconnect_connected_account(settings, "openai")

    assert request.call_args_list == [
        call(settings, "/admin/api/providers/openai/auth"),
        call(
            settings,
            "/admin/api/providers/openai/auth/login",
            method="POST",
            payload={"mode": "device"},
        ),
        call(settings, "/admin/api/providers/openai/auth/cancel", method="POST"),
        call(settings, "/admin/api/providers/openai/auth", method="DELETE"),
    ]


def test_usage_rejects_out_of_range_days_without_network() -> None:
    settings = _settings()
    with (
        patch.object(local_admin, "_request_json") as request,
        pytest.raises(ValueError, match="between 1 and 366"),
    ):
        local_admin.get_usage(settings, days=0)
    request.assert_not_called()
