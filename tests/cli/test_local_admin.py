"""Tests for the loopback terminal client of FCC's canonical Admin API."""

from unittest.mock import call, patch

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


def test_get_admin_status_reads_live_policy_receipt() -> None:
    settings = _settings()
    status = {"status": "running", "session_policy": {"provider_policy_mode": "strict"}}
    with patch.object(local_admin, "_request_json", return_value=status) as request:
        assert local_admin.get_admin_status(settings) == status

    request.assert_called_once_with(settings, "/admin/api/status")
