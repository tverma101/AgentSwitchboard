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

    run_control.assert_called_once_with(settings)
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

    attach.assert_called_once_with(settings)
    own.assert_not_called()
    port_probe.assert_not_called()


def test_control_menu_enter_launches_claude_and_returns_to_menu() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    with (
        patch("builtins.input", side_effect=["", "q"]),
        patch.object(terminal_control, "_launch_claude") as launch,
    ):
        terminal_control.run_control_menu(settings, supervisor=None)

    launch.assert_called_once_with(danger=False)


def test_attached_control_menu_refuses_to_claim_restart_ownership(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    with patch("builtins.input", side_effect=["r", "q"]):
        terminal_control.run_control_menu(settings, supervisor=None)

    assert "owned by another process" in capsys.readouterr().out


def test_owned_control_menu_routes_restart_to_supervisor() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    supervisor = MagicMock()
    supervisor.status.value = "Running"
    supervisor.request_restart.return_value = True

    with patch("builtins.input", side_effect=["r", "q"]):
        terminal_control.run_control_menu(settings, supervisor=supervisor)

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

    owner.assert_called_once_with(settings, ["--model", "muse"])


def test_direct_danger_launch_preserves_skip_permissions_through_startup() -> None:
    from free_claude_code.cli.launchers import claude

    settings = _settings()
    with (
        patch.object(claude, "get_settings", return_value=settings),
        patch.object(claude, "preflight_proxy", return_value="connection refused"),
        patch.object(claude, "_start_interactive_owner", return_value=True) as owner,
    ):
        claude.launch_danger(())

    owner.assert_called_once_with(settings, ["--dangerously-skip-permissions"])


def test_direct_owner_rejects_foreign_port_occupant() -> None:
    from free_claude_code.cli import server_startup, terminal_control
    from free_claude_code.cli.launchers import claude

    settings = _settings(port=31339)
    with (
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(server_startup, "server_port_is_occupied", return_value=True),
        patch.object(terminal_control, "run_owned_control_center") as owner,
        pytest.raises(SystemExit, match="1"),
    ):
        claude._start_interactive_owner(settings, ())

    owner.assert_not_called()


def test_noninteractive_direct_launch_does_not_create_hidden_server_owner() -> None:
    from free_claude_code.cli import server_startup, terminal_control
    from free_claude_code.cli.launchers import claude

    settings = _settings()
    with (
        patch.object(terminal_control, "terminal_control_available", return_value=False),
        patch.object(server_startup, "server_port_is_occupied") as port_probe,
        patch.object(terminal_control, "run_owned_control_center") as owner,
    ):
        started = claude._start_interactive_owner(settings, ())

    assert started is False
    port_probe.assert_not_called()
    owner.assert_not_called()
