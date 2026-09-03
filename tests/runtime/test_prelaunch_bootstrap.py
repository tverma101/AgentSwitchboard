"""Tests for the serverless native-control-center launch boundary."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    return Settings.model_construct(
        host="127.0.0.1",
        port=8082,
        model="provider/one",
    )


def test_bootstrap_result_round_trip_is_private_and_versioned(tmp_path: Path) -> None:
    from free_claude_code.runtime import bootstrap

    path = tmp_path / "result.json"
    payload = {
        "version": bootstrap.BOOTSTRAP_VERSION,
        "values": {"MODEL": "provider/two"},
        "selected_repository": None,
        "start_server": True,
    }

    bootstrap.write_bootstrap_json(path, payload)

    assert bootstrap.read_bootstrap_result(path) == payload
    assert path.stat().st_mode & 0o777 == 0o600


def test_apply_bootstrap_result_commits_then_reads_model_values_back() -> None:
    from free_claude_code.runtime import bootstrap

    prepared = MagicMock(valid=True, errors=())
    loaded_settings = _settings()
    state = {"MODEL": {"value": "provider/two", "source": "managed_env"}}
    config = {"fields": [{"key": "MODEL"}]}
    payload = {
        "version": bootstrap.BOOTSTRAP_VERSION,
        "values": {"MODEL": "provider/two"},
        "selected_repository": None,
        "start_server": True,
    }

    with (
        patch(
            "free_claude_code.config.admin.persistence.prepare_admin_update",
            return_value=prepared,
        ) as prepare,
        patch(
            "free_claude_code.config.admin.persistence.commit_prepared_admin_update"
        ) as commit,
        patch(
            "free_claude_code.config.admin.values.load_value_state",
            return_value=state,
        ),
        patch(
            "free_claude_code.config.admin.values.load_config_response",
            return_value=config,
        ),
        patch.object(
            bootstrap, "get_settings", return_value=loaded_settings
        ) as load_settings,
    ):
        result = bootstrap.apply_bootstrap_result(payload)

    prepare.assert_called_once_with({"MODEL": "provider/two"})
    commit.assert_called_once_with(prepared)
    load_settings.cache_clear.assert_called_once_with()
    assert result is loaded_settings


def test_build_bootstrap_state_carries_direct_launch_intent_without_secrets() -> None:
    from free_claude_code.runtime import bootstrap

    snapshot = {
        "version": bootstrap.BOOTSTRAP_VERSION,
        "config": {"fields": []},
        "models": {"models": []},
    }
    with patch.object(
        bootstrap,
        "_build_prelaunch_state",
        new=AsyncMock(return_value=snapshot),
    ) as build:
        result = bootstrap.build_bootstrap_state(
            _settings(),
            launch_after_repository=True,
            launch_danger=True,
        )

    build.assert_awaited_once()
    assert result["launch_after_repository"] is True
    assert result["launch_danger"] is True
    assert "api_key" not in result


@pytest.mark.parametrize(
    ("danger", "argv"),
    (
        (False, ("--model", "provider/one")),
        (True, ("--dangerously-skip-permissions",)),
    ),
)
def test_owned_control_center_hands_saved_repository_to_requested_claude_mode(
    tmp_path: Path,
    danger: bool,
    argv: tuple[str, ...],
) -> None:
    from free_claude_code.cli import control_tui_entry

    settings = _settings()
    repository = tmp_path / "selected-repository"
    repository.mkdir()
    supervisor = MagicMock()
    supervisor.schedule_run.return_value = True
    server_thread = MagicMock()
    launch = MagicMock()
    result = {
        "version": 1,
        "values": {"MODEL": "nvidia_nim/moonshotai/kimi-k3"},
        "selected_repository": str(repository),
        "start_server": True,
    }

    with (
        patch.object(
            control_tui_entry, "build_bootstrap_state", return_value={}
        ) as build,
        patch.object(control_tui_entry, "write_bootstrap_json"),
        patch.object(control_tui_entry, "run_native_control_center"),
        patch.object(control_tui_entry, "read_bootstrap_result", return_value=result),
        patch.object(
            control_tui_entry, "apply_bootstrap_result", return_value=settings
        ),
        patch.object(control_tui_entry, "ServerSupervisor", return_value=supervisor),
        patch.object(control_tui_entry.threading, "Thread", return_value=server_thread),
        patch.object(control_tui_entry, "_wait_for_proxy", return_value=None),
        patch.object(control_tui_entry, "run_control_tui"),
    ):
        control_tui_entry.run_owned_control_center(
            settings,
            initial_argv=argv,
            initial_cwd=tmp_path / "wrong-fallback",
            initial_danger=danger,
            launch_client=launch,
        )

    build.assert_called_once_with(
        settings,
        launch_after_repository=True,
        launch_danger=danger,
    )
    launch.assert_called_once_with(
        danger,
        argv,
        repository,
    )
    supervisor.request_stop.assert_called_once_with()
