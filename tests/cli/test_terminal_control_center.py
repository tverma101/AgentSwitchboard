"""Behavior tests for the terminal FCC server control surface."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings


def _settings(*, port: int = 8082) -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=port,
        anthropic_auth_token="freecc",
        model="opencode_go/muse-spark-1.2-contributor",
        reasoning_policy=ReasoningPreference.CLIENT,
    )


def test_interactive_fcc_server_owns_control_center_when_proxy_is_down() -> None:
    from free_claude_code.cli import commands, entrypoints, terminal_control

    settings = _settings()
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value="not running",
        ),
        patch.object(entrypoints, "_server_port_is_occupied", return_value=False),
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(terminal_control, "run_owned_control_center") as run_control,
        patch.object(commands, "serve") as raw_server,
    ):
        entrypoints.serve(())

    run_control.assert_called_once_with(
        settings,
        launch_client=entrypoints._launch_claude_from_control,
    )
    raw_server.assert_not_called()


def test_headless_fcc_server_preserves_blocking_server_behavior() -> None:
    from free_claude_code.cli import commands, entrypoints, terminal_control

    settings = _settings()
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value="not running",
        ),
        patch.object(entrypoints, "_server_port_is_occupied", return_value=False),
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(terminal_control, "run_owned_control_center") as run_control,
        patch.object(commands, "serve") as raw_server,
    ):
        entrypoints.serve(("--headless",))

    run_control.assert_not_called()
    raw_server.assert_called_once_with()


def test_interactive_fcc_server_attaches_to_existing_proxy_without_ownership() -> None:
    from free_claude_code.cli import commands, entrypoints, terminal_control

    settings = _settings(port=31337)
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value=None,
        ),
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(terminal_control, "run_attached_control_center") as attach,
        patch.object(terminal_control, "run_owned_control_center") as own,
        patch.object(entrypoints, "_server_port_is_occupied") as port_probe,
    ):
        entrypoints.serve(())

    attach.assert_called_once_with(
        settings,
        launch_client=entrypoints._launch_claude_from_control,
    )
    own.assert_not_called()
    port_probe.assert_not_called()


def test_control_menu_enter_launches_claude_and_returns_to_menu() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    with patch("builtins.input", side_effect=["", "q"]):
        launch = MagicMock()
        terminal_control.run_control_menu(
            settings,
            supervisor=None,
            launch_client=launch,
        )

    launch.assert_called_once_with(False, ())


def test_home_redraw_uses_passed_settings_without_admin_io(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    with patch.object(
        terminal_control,
        "get_admin_config",
        side_effect=AssertionError("home redraw must not call Admin"),
    ):
        terminal_control._print_home(settings, supervisor=None)

    output = capsys.readouterr().out
    assert f"Model     {settings.model}" in output


def test_attached_control_menu_refuses_to_claim_restart_ownership(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    with patch("builtins.input", side_effect=["r", "q"]):
        terminal_control.run_control_menu(
            settings,
            supervisor=None,
            launch_client=MagicMock(),
        )

    assert "owned by another process" in capsys.readouterr().out


def test_owned_control_menu_routes_restart_to_supervisor() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    supervisor = MagicMock()
    supervisor.status.value = "Running"
    supervisor.request_restart.return_value = True

    with patch("builtins.input", side_effect=["r", "q"]):
        terminal_control.run_control_menu(
            settings,
            supervisor=supervisor,
            launch_client=MagicMock(),
        )

    supervisor.request_restart.assert_called_once_with()


def test_log_preview_formats_structured_json_and_keeps_plain_lines(
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.terminal_control import _render_log_line, _tail_lines

    log = tmp_path / "server.log"
    log.write_text(
        "old\n"
        '{"time":"2026-08-25T12:30:01.123-04:00","level":"INFO","message":"ready"}\n'
        "plain fallback\n",
        encoding="utf-8",
    )

    lines = _tail_lines(log, limit=2)
    assert len(lines) == 2
    assert _render_log_line(lines[0]).endswith("INFO     ready")
    assert _render_log_line(lines[1]) == "plain fallback"


def test_direct_claude_launch_uses_owned_control_center_when_proxy_is_down() -> None:
    from free_claude_code.cli.launchers import claude

    settings = _settings()
    with (
        patch.object(claude, "get_settings", return_value=settings),
        patch.object(claude, "preflight_proxy", return_value="connection refused"),
        patch.object(claude, "_start_interactive_owner", return_value=True) as owner,
    ):
        claude.launch(("--model", "muse"))

    owner.assert_called_once_with(["--model", "muse"])


def test_direct_danger_launch_preserves_skip_permissions_through_startup() -> None:
    from free_claude_code.cli.launchers import claude

    settings = _settings()
    with (
        patch.object(claude, "get_settings", return_value=settings),
        patch.object(claude, "preflight_proxy", return_value="connection refused"),
        patch.object(claude, "_start_interactive_owner", return_value=True) as owner,
    ):
        claude.launch_danger(())

    owner.assert_called_once_with(["--dangerously-skip-permissions"])


def test_direct_owner_starts_control_center_with_post_migration_settings() -> None:
    from free_claude_code.cli import commands, server_startup, terminal_control
    from free_claude_code.cli.launchers import claude

    settings = _settings(port=31338)
    with (
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(commands, "load_server_settings", return_value=settings) as load,
        patch.object(claude, "preflight_proxy", return_value="connection refused"),
        patch.object(server_startup, "server_port_is_occupied", return_value=False),
        patch.object(terminal_control, "run_owned_control_center") as owner,
        patch.object(claude.get_settings, "cache_clear") as clear,
    ):
        started = claude._start_interactive_owner(("--model", "muse"))

    assert started is True
    clear.assert_called_once_with()
    load.assert_called_once_with()
    owner.assert_called_once_with(
        settings,
        initial_argv=("--model", "muse"),
        launch_client=claude._launch_control_client,
    )


def test_direct_owner_reuses_post_migration_server_if_it_is_already_healthy() -> None:
    from free_claude_code.cli import commands, server_startup, terminal_control
    from free_claude_code.cli.launchers import claude

    settings = _settings(port=31340)
    with (
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(commands, "load_server_settings", return_value=settings),
        patch.object(claude, "preflight_proxy", return_value=None),
        patch.object(server_startup, "server_port_is_occupied") as port_probe,
        patch.object(terminal_control, "run_owned_control_center") as owner,
        patch.object(claude, "launch") as relaunch,
        patch.object(claude.get_settings, "cache_clear"),
    ):
        started = claude._start_interactive_owner(("--model", "muse"))

    assert started is True
    relaunch.assert_called_once_with(("--model", "muse"))
    port_probe.assert_not_called()
    owner.assert_not_called()


def test_owned_control_center_launches_initial_client_after_health() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    supervisor = MagicMock()
    supervisor.schedule_run.return_value = True
    server_thread = MagicMock()
    launch = MagicMock()

    with (
        patch.object(terminal_control, "ServerSupervisor", return_value=supervisor),
        patch.object(terminal_control.threading, "Thread", return_value=server_thread),
        patch.object(terminal_control, "_wait_for_proxy", return_value=None),
        patch.object(terminal_control, "run_control_menu") as menu,
    ):
        terminal_control.run_owned_control_center(
            settings,
            initial_argv=("--model", "muse"),
            launch_client=launch,
        )

    server_thread.start.assert_called_once_with()
    launch.assert_called_once_with(False, ("--model", "muse"))
    menu.assert_called_once_with(
        settings,
        supervisor=supervisor,
        launch_client=launch,
    )
    supervisor.request_stop.assert_called_once_with()
    server_thread.join.assert_called_once_with()


def test_direct_owner_rejects_foreign_port_occupant() -> None:
    from free_claude_code.cli import commands, server_startup, terminal_control
    from free_claude_code.cli.launchers import claude

    settings = _settings(port=31339)
    with (
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(commands, "load_server_settings", return_value=settings),
        patch.object(claude, "preflight_proxy", return_value="connection refused"),
        patch.object(server_startup, "server_port_is_occupied", return_value=True),
        patch.object(terminal_control, "run_owned_control_center") as owner,
        patch.object(claude.get_settings, "cache_clear"),
        pytest.raises(SystemExit, match="1"),
    ):
        claude._start_interactive_owner(())

    owner.assert_not_called()


def test_noninteractive_direct_launch_does_not_create_hidden_server_owner() -> None:
    from free_claude_code.cli import commands, server_startup, terminal_control
    from free_claude_code.cli.launchers import claude

    with (
        patch.object(
            terminal_control, "terminal_control_available", return_value=False
        ),
        patch.object(commands, "load_server_settings") as load,
        patch.object(server_startup, "server_port_is_occupied") as port_probe,
        patch.object(terminal_control, "run_owned_control_center") as owner,
    ):
        started = claude._start_interactive_owner(())

    assert started is False
    load.assert_not_called()
    port_probe.assert_not_called()
    owner.assert_not_called()
