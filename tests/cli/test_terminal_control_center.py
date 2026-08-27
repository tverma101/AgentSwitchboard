"""Behavior tests for the terminal FCC server control surface."""

import os
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
    from free_claude_code.cli import (
        commands,
        control_tui_entry,
        entrypoints,
        terminal_control,
    )

    settings = _settings()
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value="not running",
        ),
        patch.object(entrypoints, "_server_port_is_occupied", return_value=False),
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(control_tui_entry, "run_owned_control_center") as run_control,
        patch.object(commands, "serve") as raw_server,
    ):
        entrypoints.serve(())

    run_control.assert_called_once_with(
        settings,
        launch_client=entrypoints._launch_claude_from_control,
    )
    raw_server.assert_not_called()


def test_headless_fcc_server_preserves_blocking_server_behavior() -> None:
    from free_claude_code.cli import (
        commands,
        control_tui_entry,
        entrypoints,
        terminal_control,
    )

    settings = _settings()
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value="not running",
        ),
        patch.object(entrypoints, "_server_port_is_occupied", return_value=False),
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(control_tui_entry, "run_owned_control_center") as run_control,
        patch.object(commands, "serve") as raw_server,
    ):
        entrypoints.serve(("--headless",))

    run_control.assert_not_called()
    raw_server.assert_called_once_with()


def test_interactive_fcc_server_attaches_to_existing_proxy_without_ownership() -> None:
    from free_claude_code.cli import (
        commands,
        control_tui_entry,
        entrypoints,
        terminal_control,
    )

    settings = _settings(port=31337)
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value=None,
        ),
        patch.object(terminal_control, "terminal_control_available", return_value=True),
        patch.object(control_tui_entry, "run_attached_control_center") as attach,
        patch.object(control_tui_entry, "run_owned_control_center") as own,
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


def test_home_redraw_uses_local_snapshot_without_admin_io(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import terminal_control

    with patch.object(
        terminal_control,
        "get_admin_config",
        side_effect=AssertionError("home redraw must not call Admin"),
    ):
        terminal_control._print_home(
            _settings(),
            supervisor=None,
            model="cached/model",
        )

    output = capsys.readouterr().out
    assert "cached/model" in output
    assert "[P] Providers" in output
    assert "[M] Models" in output


def test_home_redraw_labels_fcc_and_codex_accounts_independently(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import terminal_control

    with (
        patch.object(
            terminal_control,
            "fcc_provider_account_summary",
            return_value="fcc@example.com",
        ),
        patch.object(
            terminal_control.codex_accounts,
            "active_account_summary",
            return_value="codex@example.com (profile work)",
        ),
    ):
        terminal_control._print_home(_settings(), supervisor=None)

    output = capsys.readouterr().out
    assert "FCC Account  fcc@example.com" in output
    assert "Codex Tools  codex@example.com (profile work)" in output


def test_provider_secret_edit_does_not_echo_value() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    field = {
        "label": "Provider API Key",
        "secret": True,
        "configured": True,
        "locked": False,
    }
    secret = "super-secret-provider-key"
    with (
        patch("builtins.input", return_value="1"),
        patch.object(terminal_control.getpass, "getpass", return_value=secret),
        patch.object(
            terminal_control,
            "apply_admin_values",
            return_value={"applied": True, "valid": True},
        ) as apply,
        patch("builtins.print") as printed,
    ):
        terminal_control._edit_provider_fields(
            settings,
            (("PROVIDER_API_KEY", field),),
        )

    apply.assert_called_once_with(settings, {"PROVIDER_API_KEY": secret})
    printed.assert_any_call("Applied PROVIDER_API_KEY.")
    assert all(secret not in str(call_args) for call_args in printed.call_args_list)


def test_provider_field_mapping_uses_catalog_owned_settings_attributes() -> None:
    from free_claude_code.cli import terminal_control

    config = {
        "fields": [
            {
                "key": "NVIDIA_NIM_API_KEY",
                "label": "NVIDIA NIM API Key",
                "secret": True,
                "configured": False,
            },
            {
                "key": "OPENAI_PROXY",
                "label": "OpenAI Proxy",
                "secret": True,
                "configured": False,
            },
        ]
    }

    nim_fields = terminal_control._provider_fields(config, "nvidia_nim")
    openai_fields = terminal_control._provider_fields(config, "openai")

    assert [key for key, _field in nim_fields] == ["NVIDIA_NIM_API_KEY"]
    assert [key for key, _field in openai_fields] == ["OPENAI_PROXY"]


def test_provider_filter_uses_shared_picker() -> None:
    from free_claude_code.cli import terminal_control

    statuses = [
        {
            "provider_id": "openai",
            "display_name": "OpenAI",
            "label": "Configured",
        }
    ]
    item = terminal_control.SelectionItem("openai", "OpenAI", "Configured")
    with patch.object(terminal_control, "choose_item", return_value=item) as choose:
        selected = terminal_control._select_provider(statuses, "ope")

    assert selected is statuses[0]
    choose.assert_called_once()


def test_model_menu_selects_through_shared_picker() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    item = terminal_control.SelectionItem("opencode_go/selected", "selected")
    with (
        patch.object(
            terminal_control,
            "get_models",
            return_value={
                "models": [item.item_id],
                "model_labels": {},
                "model_evidence": {},
            },
        ),
        patch.object(terminal_control, "choose_item", return_value=item) as choose,
        patch.object(
            terminal_control,
            "apply_admin_values",
            return_value={"applied": True},
        ) as apply,
        patch("builtins.input", return_value="s"),
    ):
        assert terminal_control._run_models_menu(settings) == item.item_id

    choose.assert_called_once()
    apply.assert_called_once_with(settings, {"MODEL": item.item_id})


def test_model_items_include_friendly_label_and_evidence() -> None:
    from free_claude_code.cli import terminal_control

    items = terminal_control._model_items(
        {
            "models": ["gateway/model"],
            "model_labels": {"gateway/model": "Gateway Model"},
            "model_evidence": {
                "gateway/model": {"evidence_source": "provider_metadata"}
            },
        }
    )

    assert items == [
        terminal_control.SelectionItem(
            "gateway/model",
            "Gateway Model · gateway/model",
            "provider_metadata",
        )
    ]


def test_custom_provider_editor_hides_credentials() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    secret = "super-secret-custom-key"
    with (
        patch(
            "builtins.input",
            side_effect=[
                "gateway",
                "Gateway",
                "http://127.0.0.1:9000/v1",
                "n",
                "local-model",
            ],
        ),
        patch.object(
            terminal_control.getpass,
            "getpass",
            side_effect=[secret, "http://127.0.0.1:8080"],
        ),
        patch.object(
            terminal_control,
            "apply_custom_provider",
            return_value={"applied": True},
        ) as apply,
        patch("builtins.print") as printed,
    ):
        assert terminal_control._edit_custom_provider(settings) is True

    apply.assert_called_once_with(
        settings,
        {
            "id": "gateway",
            "display_name": "Gateway",
            "base_url": "http://127.0.0.1:9000/v1",
            "local": False,
            "models": ["local-model"],
            "api_key": secret,
            "proxy": "http://127.0.0.1:8080",
        },
        existing_provider_id=None,
    )
    assert all(secret not in str(call_args) for call_args in printed.call_args_list)


def test_connected_account_detail_uses_explicit_browser_login_action() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    provider = {
        "provider_id": "openai",
        "display_name": "OpenAI / ChatGPT",
        "label": "Not connected",
    }
    with (
        patch.object(
            terminal_control,
            "connected_account_status",
            return_value={"state": "disconnected"},
        ),
        patch.object(
            terminal_control,
            "start_connected_account_login",
            return_value={
                "state": "connecting",
                "authorization_url": "https://example.test/device",
            },
        ) as start,
        patch("builtins.input", side_effect=["l", "b"]),
    ):
        terminal_control._run_provider_detail(settings, provider, {"fields": []})

    start.assert_called_once_with(
        settings,
        "openai",
        terminal_control.ConnectedAccountLoginMode.BROWSER,
    )


def test_control_menu_policy_command_prints_live_status() -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    with (
        patch("builtins.input", side_effect=["y", "q"]),
        patch.object(terminal_control, "_print_policy_status") as print_status,
    ):
        terminal_control.run_control_menu(
            settings,
            supervisor=None,
            launch_client=MagicMock(),
        )

    print_status.assert_called_once_with(settings)


def test_policy_status_print_is_metadata_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import terminal_control

    settings = _settings()
    with patch.object(
        terminal_control,
        "get_admin_status",
        return_value={
            "session_policy": {
                "controller_provider": "opencode_go",
                "controller_model": "muse-spark-1.2-contributor",
                "provider_policy_mode": "strict",
                "capability_routing_mode": "smart_local",
                "allowed_helpers": ["codex-computer-use"],
                "paid_fallback": False,
                "egress": {"counts": {}, "blocked_counts": {}},
            }
        },
    ):
        terminal_control._print_policy_status(settings)

    output = capsys.readouterr().out
    assert "opencode_go/muse-spark-1.2-contributor" in output
    assert "codex-computer-use" in output
    assert "strict" in output


def test_selected_profile_and_repo_are_forwarded_without_mutating_server_state(
    tmp_path: Path,
) -> None:
    from free_claude_code.cli import terminal_control
    from free_claude_code.learning.config import PROFILE_ENV

    repo = terminal_control.RepoEntry(
        "selected",
        str(tmp_path / "selected"),
        "main",
        "acme/selected",
    )
    launch = MagicMock()
    with patch.dict("os.environ", {}, clear=False):
        os.environ.pop(PROFILE_ENV, None)
        terminal_control._launch_selected(
            launch,
            danger=True,
            profile="coding",
            repo=repo,
        )

    launch.assert_called_once_with(
        True,
        ("--profile", "coding"),
        Path(repo.path),
    )
    assert PROFILE_ENV not in os.environ


def test_profile_menu_selection_is_next_launch_only() -> None:
    from free_claude_code.cli import terminal_control

    with (
        patch.object(
            terminal_control, "list_profiles", return_value=("default", "coding")
        ),
        patch.object(terminal_control, "list_archived_profiles", return_value=()),
        patch.object(terminal_control, "_choose_profile", return_value="coding"),
        patch("builtins.input", side_effect=["s", "b"]),
    ):
        selected = terminal_control._run_profile_menu("default")

    assert selected == "coding"


def test_repo_menu_uses_cached_repo_picker_and_records_last_use(
    tmp_path: Path,
) -> None:
    from free_claude_code.cli import terminal_control

    cache = tmp_path / "repos.json"
    repo = terminal_control.RepoEntry(
        "selected",
        str(tmp_path / "selected"),
        "main",
        "acme/selected",
    )
    with (
        patch.object(terminal_control, "cache_path", return_value=cache),
        patch.object(terminal_control, "load_cached_repos", return_value=[repo]),
        patch.object(terminal_control, "cache_is_fresh", return_value=True),
        patch.object(terminal_control, "choose_repo", return_value=repo),
        patch.object(terminal_control, "save_cached_repos") as save,
        patch("builtins.input", return_value="s"),
    ):
        selected = terminal_control._run_repo_menu(None)

    assert selected == repo
    save.assert_called_once()
    assert save.call_args.args[1] == cache


def test_bundle_menu_previews_import_before_apply(
    tmp_path: Path,
) -> None:
    from free_claude_code.cli import terminal_control

    bundle = tmp_path / "portable.bundle"
    store = MagicMock()
    preview = {
        "selected": {"memories": 1, "skills": 0},
        "actions": [{"kind": "memory", "key": "a" * 64, "action": "add"}],
    }
    applied = {**preview, "applied": {"memories": 1, "skills": 0}}
    with (
        patch.object(terminal_control, "project_identity", return_value="project"),
        patch.object(terminal_control, "LearningStore", return_value=store),
        patch.object(terminal_control, "claude_config_dir", return_value=tmp_path),
        patch.object(
            terminal_control, "import_bundle", side_effect=[preview, applied]
        ) as imp,
        patch(
            "builtins.input",
            side_effect=["i", str(bundle), "skip", "", "", "y", "b"],
        ),
    ):
        terminal_control._run_bundle_menu("coding")

    assert imp.call_count == 2
    assert imp.call_args_list[0].kwargs["dry_run"] is True
    assert imp.call_args_list[1].kwargs["dry_run"] is False


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
