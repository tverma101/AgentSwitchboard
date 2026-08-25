"""Terminal settings behavior over the canonical Admin API."""

from unittest.mock import patch

from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        model="opencode_go/muse-spark-1.2-contributor",
        reasoning_policy=ReasoningPreference.CLIENT,
    )


def test_terminal_setting_refuses_locked_admin_field(capsys) -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    field = {"key": "MODEL", "locked": True, "source": "process"}
    with (
        patch("builtins.input") as user_input,
        patch.object(terminal_control, "apply_admin_values") as apply,
    ):
        terminal_control._edit_setting(
            settings,
            field,
            key="MODEL",
            prompt="Model> ",
        )

    user_input.assert_not_called()
    apply.assert_not_called()
    assert "locked by process" in capsys.readouterr().out


def test_terminal_setting_applies_value_through_admin_api() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    field = {"key": "MODEL", "locked": False, "source": "managed_env"}
    with (
        patch("builtins.input", return_value="opencode_go/minimax-m2.7"),
        patch.object(
            terminal_control,
            "apply_admin_values",
            return_value={"applied": True, "valid": True},
        ) as apply,
    ):
        terminal_control._edit_setting(
            settings,
            field,
            key="MODEL",
            prompt="Model> ",
        )

    apply.assert_called_once_with(
        settings,
        {"MODEL": "opencode_go/minimax-m2.7"},
    )


def test_reasoning_menu_uses_manifest_options_and_admin_apply() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    config = {
        "fields": [
            {
                "key": "MODEL",
                "value": settings.model,
                "locked": False,
                "source": "managed_env",
                "options": [],
            },
            {
                "key": "REASONING_POLICY",
                "value": "client",
                "locked": False,
                "source": "managed_env",
                "options": [
                    {"value": "client", "label": "From client"},
                    {"value": "high", "label": "High"},
                ],
            },
        ]
    }
    with (
        patch.object(terminal_control, "get_admin_config", return_value=config),
        patch("builtins.input", side_effect=["r", "high", "b"]),
        patch.object(
            terminal_control,
            "apply_admin_values",
            return_value={"applied": True, "valid": True},
        ) as apply,
    ):
        terminal_control._run_settings_menu(settings)

    apply.assert_called_once_with(settings, {"REASONING_POLICY": "high"})
