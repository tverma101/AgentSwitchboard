"""Tests for installed CLI entrypoints, commands, and launchers."""

import json
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import URLError
from urllib.request import Request

import pytest

from free_claude_code.config.settings import Settings


def _launcher_settings(
    *,
    port: int = 8082,
    token: str = "freecc",
    allowed_helpers: str = "",
) -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=port,
        anthropic_auth_token=token,
        model="nvidia_nim/test-model",
        allowed_helper_ids=allowed_helpers,
    )


class _JsonResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> _JsonResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_legacy_env_migration_supports_xdg_path(tmp_path: Path) -> None:
    """Server startup preserves config from ~/.config/free-claude-code/.env."""
    from free_claude_code.cli.commands import _migrate_legacy_env_if_missing

    legacy_env = tmp_path / ".config" / "free-claude-code" / ".env"
    legacy_env.parent.mkdir(parents=True)
    legacy_env.write_text("MODEL=open_router/free-model\n", encoding="utf-8")

    with patch("pathlib.Path.home", return_value=tmp_path):
        migrated_from = _migrate_legacy_env_if_missing()

    env_file = tmp_path / ".fcc" / ".env"
    assert migrated_from == legacy_env
    assert env_file.read_text("utf-8") == "MODEL=open_router/free-model\n"


def test_legacy_env_migration_does_not_overwrite_managed_env(
    tmp_path: Path,
) -> None:
    """Legacy migration never overwrites an existing ~/.fcc/.env."""
    from free_claude_code.cli.commands import _migrate_legacy_env_if_missing

    managed_env = tmp_path / ".fcc" / ".env"
    managed_env.parent.mkdir(parents=True)
    managed_env.write_text("MODEL=nvidia_nim/current\n", encoding="utf-8")
    legacy_env = tmp_path / "free-claude-code" / ".env"
    legacy_env.parent.mkdir(parents=True)
    legacy_env.write_text("MODEL=deepseek/legacy\n", encoding="utf-8")

    with patch("pathlib.Path.home", return_value=tmp_path):
        migrated_from = _migrate_legacy_env_if_missing()

    assert migrated_from is None
    assert managed_env.read_text("utf-8") == "MODEL=nvidia_nim/current\n"


def test_cli_scripts_are_registered() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert pyproject["project"]["scripts"] == {
        "fcc": "free_claude_code.cli.entrypoints:main",
        "fcc-server": "free_claude_code.cli.entrypoints:serve",
        "fcc-claude": "free_claude_code.cli.launchers.claude:launch",
        "fccdanger": "free_claude_code.cli.launchers.claude:launch_danger",
        "fcc-codex": "free_claude_code.cli.launchers.codex:launch",
        "fcc-pi": "free_claude_code.cli.launchers.pi:launch",
        "fcc-learning": "free_claude_code.learning.cli:main",
        "fcc-appshot": "free_claude_code.cli.appshot:main",
        "fcc-attachment": "free_claude_code.cli.attachment:main",
        "fcc-browser": "free_claude_code.cli.browser:main",
        "fcc-diagnose": "free_claude_code.cli.diagnose:main",
        "fcc-repos": "free_claude_code.cli.repo_picker:main",
    }
    assert pyproject["project"]["gui-scripts"] == {
        "fcc-desktop": "free_claude_code.cli.desktop_entrypoint:launch",
    }


@pytest.mark.parametrize(
    "argv",
    [("--version",), ("--version", "--help"), ("--help", "--version")],
)
def test_fcc_server_reports_version_without_side_effects(
    argv: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import entrypoints

    with patch.object(entrypoints, "package_version", return_value="9.8.7"):
        entrypoints.serve(argv)

    assert capsys.readouterr() == ("free-claude-code 9.8.7\n", "")


def test_version_entrypoint_does_not_import_command_runtime() -> None:
    script = "\n".join(
        (
            "import json",
            "import sys",
            "from free_claude_code.cli.entrypoints import serve",
            "serve(['--version'])",
            "forbidden = ('uvicorn', 'fastapi', 'openai', "
            "'free_claude_code.cli.commands', "
            "'free_claude_code.runtime.bootstrap')",
            "print(json.dumps([name for name in forbidden if name in sys.modules]))",
        )
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.splitlines()[-1]) == []


def test_non_version_entrypoint_delegates_to_server_command() -> None:
    from free_claude_code.cli import commands, entrypoints

    settings = _launcher_settings()
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value="not running",
        ),
        patch.object(entrypoints, "_server_port_is_occupied", return_value=False),
        patch.object(commands, "serve") as command,
    ):
        entrypoints.serve(())

    command.assert_called_once_with()


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--terminal",),
        ("--no-browser",),
    ],
)
def test_fcc_server_options_are_terminal_only(args) -> None:
    from free_claude_code.cli.entrypoints import _parse_server_options

    assert _parse_server_options(args) is None


def test_fcc_server_rejects_browser_option() -> None:
    from free_claude_code.cli.entrypoints import _parse_server_options

    with pytest.raises(SystemExit, match="2"):
        _parse_server_options(("--open-browser",))


def test_entrypoint_reports_existing_server_without_second_bind(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import commands, entrypoints

    settings = _launcher_settings(port=31337)
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value=None,
        ),
        patch.object(commands, "serve") as run_server,
        patch.object(entrypoints, "_server_port_is_occupied") as port_probe,
    ):
        entrypoints.serve(())

    run_server.assert_not_called()
    port_probe.assert_not_called()
    assert "FCC server is already running" in capsys.readouterr().out


def test_explicit_terminal_mode_is_a_no_op_compatibility_flag() -> None:
    from free_claude_code.cli import commands, entrypoints

    settings = _launcher_settings(port=31338)
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value="not running",
        ),
        patch.object(entrypoints, "_server_port_is_occupied", return_value=False),
        patch.object(commands, "serve") as run_server,
    ):
        entrypoints.serve(("--terminal",))

    run_server.assert_called_once_with()


def test_entrypoint_reports_unrelated_port_occupant(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import commands, entrypoints

    settings = _launcher_settings(port=31339)
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value="returned HTTP 404",
        ),
        patch.object(entrypoints, "_server_port_is_occupied", return_value=True),
        patch.object(commands, "serve") as run_server,
        pytest.raises(SystemExit, match="1"),
    ):
        entrypoints.serve(())

    run_server.assert_not_called()
    assert "not an FCC health endpoint" in capsys.readouterr().err


def test_serve_is_terminal_only() -> None:
    from free_claude_code.cli import commands

    settings = _launcher_settings()
    get_settings = MagicMock(return_value=settings)
    get_settings.cache_clear = MagicMock()

    with (
        patch.object(commands, "get_settings", get_settings),
        patch.object(
            commands.ServerSupervisor, "_run_once", return_value=False
        ) as run_server,
        patch.object(commands, "kill_all_best_effort"),
    ):
        commands.serve()

    run_server.assert_called_once_with(
        settings,
        restart_generation=0,
    )


def test_serve_supervisor_restarts_when_app_requests_restart() -> None:
    from free_claude_code.cli import commands

    settings = _launcher_settings()
    get_settings = MagicMock(side_effect=[settings, settings])
    get_settings.cache_clear = MagicMock()
    servers: list[object] = []
    restart_callbacks: list[Callable[[], None]] = []

    apps: list[SimpleNamespace] = []

    def build_asgi_app(_settings: Settings, restart_callback: Callable[[], None]):
        restart_callbacks.append(restart_callback)
        app = SimpleNamespace(runtime=SimpleNamespace(is_closed=False))
        apps.append(app)
        return app

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False
            servers.append(self)

        def run(self):
            if len(servers) == 1:
                restart_callbacks[-1]()
                assert self.should_exit is True
                self.config.app.runtime.is_closed = True

    def fake_config(app, **kwargs):
        return SimpleNamespace(app=app, kwargs=kwargs)

    with (
        patch.object(commands, "get_settings", get_settings),
        patch.object(commands.uvicorn, "Config", side_effect=fake_config),
        patch.object(commands.uvicorn, "Server", side_effect=FakeServer),
        patch.object(commands, "build_asgi_app", side_effect=build_asgi_app),
        patch.object(commands, "kill_all_best_effort") as kill_all,
    ):
        commands.serve()

    assert len(servers) == 2
    get_settings.cache_clear.assert_called_once()
    kill_all.assert_called_once()


def test_serve_supervisor_refuses_restart_after_incomplete_shutdown() -> None:
    from free_claude_code.cli import commands

    settings = _launcher_settings()
    get_settings = MagicMock(return_value=settings)
    get_settings.cache_clear = MagicMock()
    servers: list[object] = []
    restart_callbacks: list[Callable[[], None]] = []

    def build_asgi_app(_settings: Settings, restart_callback: Callable[[], None]):
        restart_callbacks.append(restart_callback)
        return SimpleNamespace(runtime=SimpleNamespace(is_closed=False))

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False
            servers.append(self)

        def run(self):
            restart_callbacks[-1]()
            assert self.should_exit is True

    def fake_config(app, **kwargs):
        return SimpleNamespace(app=app, kwargs=kwargs)

    with (
        patch.object(commands, "get_settings", get_settings),
        patch.object(commands.uvicorn, "Config", side_effect=fake_config),
        patch.object(commands.uvicorn, "Server", side_effect=FakeServer),
        patch.object(commands, "build_asgi_app", side_effect=build_asgi_app),
        patch.object(commands, "kill_all_best_effort") as kill_all,
    ):
        commands.serve()

    assert len(servers) == 1
    get_settings.cache_clear.assert_not_called()
    kill_all.assert_called_once()


def test_serve_migrates_legacy_env_before_loading_settings(tmp_path: Path) -> None:
    from free_claude_code.cli import commands

    legacy_env = tmp_path / "free-claude-code" / ".env"
    legacy_env.parent.mkdir(parents=True)
    legacy_env.write_text("MODEL=deepseek/deepseek-chat\n", encoding="utf-8")
    settings = _launcher_settings()
    get_settings = MagicMock(return_value=settings)
    get_settings.cache_clear = MagicMock()

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(commands, "get_settings", get_settings),
        patch.object(commands.ServerSupervisor, "_run_once", return_value=False),
        patch.object(commands, "kill_all_best_effort"),
    ):
        commands.serve()

    assert (tmp_path / ".fcc" / ".env").read_text("utf-8") == (
        "MODEL=deepseek/deepseek-chat\n"
    )
    get_settings.assert_called_once_with()


def test_serve_migrates_hf_token_before_loading_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from free_claude_code.cli import commands

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("HF_TOKEN=legacy-hf\n", encoding="utf-8")
    settings = _launcher_settings()
    get_settings = MagicMock(return_value=settings)
    get_settings.cache_clear = MagicMock()
    monkeypatch.chdir(repo)

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(commands, "get_settings", get_settings),
        patch.object(commands.ServerSupervisor, "_run_once", return_value=False),
        patch.object(commands, "kill_all_best_effort"),
        patch.object(commands, "explicit_env_file_migration_warning"),
    ):
        commands.serve()

    assert (repo / ".env").read_text(encoding="utf-8") == (
        "HUGGINGFACE_API_KEY=legacy-hf\n"
    )
    get_settings.assert_called_once_with()


def test_serve_migrates_opencode_zen_prefix_before_loading_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from free_claude_code.cli import commands

    repo = tmp_path / "repo"
    repo.mkdir()
    env_file = repo / ".env"
    env_file.write_text("MODEL=opencode/model\n", encoding="utf-8")
    settings = _launcher_settings()

    def load_settings() -> Settings:
        assert env_file.read_text(encoding="utf-8") == ("MODEL=opencode_zen/model\n")
        return settings

    get_settings = MagicMock(side_effect=load_settings)
    get_settings.cache_clear = MagicMock()
    monkeypatch.chdir(repo)

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(commands, "get_settings", get_settings),
        patch.object(commands.ServerSupervisor, "_run_once", return_value=False),
        patch.object(commands, "kill_all_best_effort"),
        patch.object(commands, "explicit_env_file_migration_warning"),
    ):
        commands.serve()

    get_settings.assert_called_once_with()


def test_config_env_migration_warns_for_explicit_env_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import commands

    explicit = tmp_path / "custom.env"
    explicit.write_text("HF_TOKEN=legacy-hf\n", encoding="utf-8")

    with patch.dict(commands.os.environ, {"FCC_ENV_FILE": str(explicit)}):
        migrated = commands._migrate_config_env()

    assert migrated == ()
    assert "HF_TOKEN" in capsys.readouterr().err
    assert explicit.read_text(encoding="utf-8") == "HF_TOKEN=legacy-hf\n"


def test_serve_handles_keyboard_interrupt_without_traceback() -> None:
    from free_claude_code.cli import commands

    settings = _launcher_settings()
    get_settings = MagicMock(return_value=settings)
    get_settings.cache_clear = MagicMock()

    with (
        patch.object(commands, "get_settings", get_settings),
        patch.object(
            commands.ServerSupervisor,
            "_run_once",
            side_effect=KeyboardInterrupt,
        ),
        patch.object(commands, "kill_all_best_effort") as kill_all,
    ):
        commands.serve()

    get_settings.cache_clear.assert_not_called()
    kill_all.assert_called_once()


def test_claude_child_env_targets_current_proxy_config() -> None:
    from free_claude_code.cli.claude_env import build_claude_proxy_env

    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:9090",
        auth_token=" proxy-token ",
        base_env={
            "PATH": "keep",
            "ANTHROPIC_API_URL": "https://api.anthropic.com/v1",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_AUTH_TOKEN": "old-token",
            "ANTHROPIC_API_KEY": "official-key",
            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "0",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "0",
            "DISABLE_FEEDBACK_COMMAND": "0",
            "DISABLE_ERROR_REPORTING": "0",
            "DISABLE_TELEMETRY": "0",
        },
    )

    assert env["PATH"] == "keep"
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9090"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "proxy-token"
    assert env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "256000"
    assert "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" not in env
    assert env["DISABLE_AUTOUPDATER"] == "1"
    assert env["DISABLE_FEEDBACK_COMMAND"] == "1"
    assert env["DISABLE_ERROR_REPORTING"] == "1"
    assert env["DISABLE_TELEMETRY"] == "0"
    assert env["NO_PROXY"] == "127.0.0.1,localhost,::1"
    assert env["no_proxy"] == env["NO_PROXY"]
    assert "ANTHROPIC_API_URL" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" not in env


def test_claude_child_env_uses_sentinel_for_blank_configured_auth_token() -> None:
    from free_claude_code.cli.claude_env import build_claude_proxy_env

    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="",
        base_env={
            "ANTHROPIC_AUTH_TOKEN": "inherited-token",
            "ANTHROPIC_API_KEY": "official-key",
        },
    )

    assert env["ANTHROPIC_AUTH_TOKEN"] == "fcc-no-auth"
    assert "ANTHROPIC_API_KEY" not in env


def test_launch_claude_refuses_settings_env_routing_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail closed when Claude settings.json env would bypass the proxy."""
    from free_claude_code.cli.launchers.claude import launch

    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                    "ANTHROPIC_AUTH_TOKEN": "first-party-token",
                }
            }
        )
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(settings_dir))
    settings = _launcher_settings(port=9191, token="proxy-token")

    with (
        patch(
            "free_claude_code.cli.launchers.claude.get_settings", return_value=settings
        ),
        patch(
            "free_claude_code.cli.launchers.claude.preflight_proxy", return_value=None
        ),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-claude.cmd",
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        pytest.raises(SystemExit) as exc_info,
    ):
        launch(["--model", "sonnet"])

    assert exc_info.value.code == 2
    popen.assert_not_called()


def test_launch_danger_adds_skip_permissions_once() -> None:
    from free_claude_code.cli.launchers import claude

    with patch.object(claude, "launch") as launch:
        claude.launch_danger(("--model", "sonnet"))
        claude.launch_danger(("--dangerously-skip-permissions", "--model", "sonnet"))

    assert [entry.args[0] for entry in launch.call_args_list] == [
        ["--dangerously-skip-permissions", "--model", "sonnet"],
        ["--dangerously-skip-permissions", "--model", "sonnet"],
    ]


def test_fcc_claude_help_does_not_start_proxy_or_control_center() -> None:
    from free_claude_code.cli.launchers import claude

    with (
        patch.object(
            claude, "resolve_client_binary", return_value="resolved-claude.cmd"
        ) as resolve,
        patch.object(claude, "run_client_process") as run_client,
        patch.object(claude, "preflight_proxy") as preflight,
    ):
        claude.launch(["--help"])

    resolve.assert_called_once()
    run_client.assert_called_once()
    assert run_client.call_args.kwargs["command"] == [
        "resolved-claude.cmd",
        "--help",
    ]
    preflight.assert_not_called()


def test_launch_claude_allows_unrelated_settings_env_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Non-routing settings env keys do not block a proxy launch."""
    from free_claude_code.cli.launchers.claude import launch

    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"env": {"EDITOR": "code", "CLAUDE_MODEL": "sonnet"}})
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(settings_dir))
    settings = _launcher_settings(port=9191, token="proxy-token")

    with (
        patch(
            "free_claude_code.cli.launchers.claude.get_settings", return_value=settings
        ),
        patch(
            "free_claude_code.cli.launchers.claude.preflight_proxy", return_value=None
        ),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-claude.cmd",
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        patch("free_claude_code.cli.launchers.common.register_pid") as _register_pid,
        patch(
            "free_claude_code.cli.launchers.common.unregister_pid"
        ) as _unregister_pid,
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 12345
        process.wait.return_value = 0
        launch(["--model", "sonnet"])

    assert exc_info.value.code == 0
    popen.assert_called_once()
    child_env = popen.call_args.kwargs["env"]
    assert child_env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9191"
    assert child_env["ANTHROPIC_AUTH_TOKEN"] == "proxy-token"


def test_launch_claude_passes_args_and_child_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from free_claude_code.cli.launchers.claude import launch

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "old-token")
    monkeypatch.setenv("KEEP_ME", "yes")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(Path("/nonexistent-fcc-test-config")))
    monkeypatch.delenv("DISABLE_TELEMETRY", raising=False)
    settings = _launcher_settings(port=9191, token="proxy-token")

    with (
        patch(
            "free_claude_code.cli.launchers.claude.get_settings", return_value=settings
        ),
        patch(
            "free_claude_code.cli.launchers.claude.preflight_proxy", return_value=None
        ),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-claude.cmd",
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        patch("free_claude_code.cli.launchers.common.register_pid") as register_pid,
        patch("free_claude_code.cli.launchers.common.unregister_pid") as unregister_pid,
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 12345
        process.wait.return_value = 7
        launch(["--model", "sonnet"])

    assert exc_info.value.code == 7
    popen.assert_called_once()
    assert popen.call_args.args[0] == ["resolved-claude.cmd", "--model", "sonnet"]
    child_env = popen.call_args.kwargs["env"]
    assert child_env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9191"
    assert child_env["ANTHROPIC_AUTH_TOKEN"] == "proxy-token"
    assert child_env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"
    assert child_env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "256000"
    assert "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" not in child_env
    assert child_env["DISABLE_AUTOUPDATER"] == "1"
    assert child_env["DISABLE_FEEDBACK_COMMAND"] == "1"
    assert child_env["DISABLE_ERROR_REPORTING"] == "1"
    assert "DISABLE_TELEMETRY" not in child_env
    assert child_env["NO_PROXY"] == "127.0.0.1,localhost,::1"
    assert child_env["no_proxy"] == child_env["NO_PROXY"]
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" not in child_env
    assert child_env["KEEP_ME"] == "yes"
    register_pid.assert_called_once_with(12345)
    unregister_pid.assert_called_once_with(12345)


def test_launch_claude_prepares_enabled_computer_use_before_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.launchers import claude

    settings = _launcher_settings(
        port=9191,
        token="proxy-token",
        allowed_helpers="codex-computer-use",
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    with (
        patch.object(claude, "get_settings", return_value=settings),
        patch.object(claude, "preflight_proxy", return_value=None),
        patch.object(claude, "ensure_learning_hooks"),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-claude.cmd",
        ),
        patch.object(claude, "_prepare_computer_use_session") as prepare,
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        patch("free_claude_code.cli.launchers.common.register_pid"),
        patch("free_claude_code.cli.launchers.common.unregister_pid"),
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 12345
        process.wait.return_value = 0
        claude.launch(["--model", "sonnet"], cwd=tmp_path)

    assert exc_info.value.code == 0
    prepare.assert_called_once()
    assert prepare.call_args.args == (settings,)
    assert prepare.call_args.kwargs["claude_binary"] == "resolved-claude.cmd"
    assert prepare.call_args.kwargs["cwd"] == tmp_path
    assert prepare.call_args.kwargs["raise_for_control"] is False
    child_env = prepare.call_args.kwargs["base_env"]
    assert child_env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9191"
    assert child_env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "claude")


def test_prepare_computer_use_session_skips_unallowlisted_helper(
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.launchers import claude

    settings = _launcher_settings()
    with patch.object(claude, "resolve_official_computer_use") as resolve:
        claude._prepare_computer_use_session(
            settings,
            claude_binary="claude",
            cwd=tmp_path,
            base_env={},
            raise_for_control=True,
        )

    resolve.assert_not_called()


def test_prepare_computer_use_session_uses_active_profile_and_registers_mcp(
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.launchers import claude

    settings = _launcher_settings(allowed_helpers="codex-computer-use")
    paths = object()
    bundled_launcher = tmp_path / "bundled-launcher"
    config_dir = tmp_path / "profile" / "claude"
    project_dir = tmp_path / "project"
    environment = {
        "HOME": str(tmp_path / "home"),
        "CLAUDE_CONFIG_DIR": str(config_dir),
    }
    old_profile_launcher = (
        config_dir / "fcc/codex-computer-use/bin/computer-use-client-launcher"
    )

    with (
        patch.object(
            claude, "resolve_official_computer_use", return_value=paths
        ) as resolve,
        patch.object(claude, "install_native_computer_use_skill") as install,
        patch.object(
            claude,
            "managed_launcher",
            return_value=(tmp_path, bundled_launcher),
        ) as managed,
        patch.object(claude, "ensure_claude_local_computer_use_mcp") as register,
    ):
        claude._prepare_computer_use_session(
            settings,
            claude_binary="claude",
            cwd=project_dir,
            base_env=environment,
            raise_for_control=True,
        )

    resolve.assert_called_once_with(home=Path(environment["HOME"]))
    install.assert_called_once_with(paths, claude_config_dir=config_dir)
    managed.assert_called_once_with(paths)
    register.assert_called_once_with(
        claude_binary="claude",
        cwd=project_dir.resolve(),
        base_env=environment,
        node_executable=None,
        bridge_path=None,
        python_executable=sys.executable,
        native_launcher=old_profile_launcher,
        legacy_native_launcher=bundled_launcher,
    )


def test_prepare_computer_use_session_reports_actionable_failure(
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.launchers import claude

    settings = _launcher_settings(allowed_helpers="codex-computer-use")
    config_dir = tmp_path / "claude"

    with (
        patch.object(
            claude,
            "resolve_official_computer_use",
            side_effect=claude.CodexComputerUseError("signed client is missing"),
        ),
        pytest.raises(claude.ClientLaunchError) as exc_info,
    ):
        claude._prepare_computer_use_session(
            settings,
            claude_binary="claude",
            cwd=tmp_path,
            base_env={"CLAUDE_CONFIG_DIR": str(config_dir)},
            raise_for_control=True,
        )

    message = str(exc_info.value)
    assert exc_info.value.exit_code == 78
    assert "signed client is missing" in message
    assert str(config_dir) in message
    assert "FCC_ALLOWED_HELPERS" in message


def test_launch_claude_applies_model_context_window_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launch with a flash gateway model raises the auto-compact window."""
    from free_claude_code.cli.launchers.claude import launch

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(Path("/nonexistent-fcc-test-config")))
    settings = _launcher_settings(port=9191, token="proxy-token")

    with (
        patch(
            "free_claude_code.cli.launchers.claude.get_settings", return_value=settings
        ),
        patch(
            "free_claude_code.cli.launchers.claude.preflight_proxy", return_value=None
        ),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-claude.cmd",
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        patch("free_claude_code.cli.launchers.common.register_pid"),
        patch("free_claude_code.cli.launchers.common.unregister_pid"),
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 12345
        process.wait.return_value = 7
        launch(["--model", "anthropic/opencode/deepseek-v4-flash-free"])

    assert exc_info.value.code == 7
    child_env = popen.call_args.kwargs["env"]
    assert child_env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "256000"
    assert child_env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"
    assert "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" not in child_env


def test_launch_codex_passes_responses_config_and_child_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.launchers.codex import launch

    monkeypatch.setenv("OPENAI_API_KEY", "official-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("CODEX_HOME", "keep-home")
    monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "Codex Desktop")
    monkeypatch.setenv("CODEX_PERMISSION_PROFILE", "danger-full-access")
    monkeypatch.setenv("CODEX_SHELL", "1")
    monkeypatch.setenv("CODEX_THREAD_ID", "parent-thread")
    settings = _launcher_settings(port=9191, token="proxy-token")
    catalog_path = tmp_path / "codex-model-catalog.json"
    requests: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: float) -> _JsonResponse:
        requests.append(request)
        assert timeout == 1.5
        return _JsonResponse(
            {
                "data": [
                    {
                        "id": "anthropic/nvidia_nim/provider-model",
                        "display_name": "NVIDIA model",
                    },
                    {
                        "id": ("claude-3-freecc-no-thinking/nvidia_nim/provider-model"),
                        "display_name": "NVIDIA model (no thinking)",
                    },
                    {
                        "id": "claude-opus-4-20250514",
                        "display_name": "Claude Opus 4",
                    },
                ]
            }
        )

    with (
        patch(
            "free_claude_code.cli.launchers.codex.get_settings", return_value=settings
        ),
        patch(
            "free_claude_code.cli.launchers.codex.preflight_proxy", return_value=None
        ),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-codex.cmd",
        ),
        patch(
            "free_claude_code.cli.launchers.codex.codex_model_catalog_path",
            return_value=catalog_path,
        ),
        patch(
            "free_claude_code.cli.launchers.codex.open_local_request",
            side_effect=fake_urlopen,
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        patch("free_claude_code.cli.launchers.common.register_pid") as register_pid,
        patch("free_claude_code.cli.launchers.common.unregister_pid") as unregister_pid,
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 12345
        process.wait.return_value = 0
        launch(["exec", "hello"])

    assert exc_info.value.code == 0
    command = popen.call_args.args[0]
    assert command[0] == "resolved-codex.cmd"
    assert 'model_provider="fcc"' in command
    assert 'model_providers.fcc.base_url="http://127.0.0.1:9191/v1"' in command
    assert 'model_providers.fcc.wire_api="responses"' in command
    assert f"model_catalog_json={json.dumps(str(catalog_path))}" in command
    assert command[-2:] == ["exec", "hello"]
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == "http://127.0.0.1:9191/v1/models"
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["authorization"] == "Bearer proxy-token"
    assert "x-api-key" not in headers
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert [model["slug"] for model in catalog["models"]] == [
        "nvidia_nim/provider-model"
    ]
    child_env = popen.call_args.kwargs["env"]
    assert child_env["FCC_CODEX_API_KEY"] == "proxy-token"
    assert child_env["CODEX_HOME"] == "keep-home"
    assert child_env["NO_PROXY"] == "127.0.0.1,localhost,::1"
    assert child_env["no_proxy"] == child_env["NO_PROXY"]
    assert "CODEX_INTERNAL_ORIGINATOR_OVERRIDE" not in child_env
    assert "CODEX_PERMISSION_PROFILE" not in child_env
    assert "CODEX_SHELL" not in child_env
    assert "CODEX_THREAD_ID" not in child_env
    assert "OPENAI_API_KEY" not in child_env
    assert "OPENAI_BASE_URL" not in child_env
    register_pid.assert_called_once_with(12345)
    unregister_pid.assert_called_once_with(12345)


def test_launch_codex_catalog_failure_warns_and_continues(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.launchers.codex import launch

    settings = _launcher_settings(port=9191, token="proxy-token")

    with (
        patch(
            "free_claude_code.cli.launchers.codex.get_settings", return_value=settings
        ),
        patch(
            "free_claude_code.cli.launchers.codex.preflight_proxy", return_value=None
        ),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-codex.cmd",
        ),
        patch(
            "free_claude_code.cli.launchers.codex.codex_model_catalog_path",
            return_value=tmp_path / "codex-model-catalog.json",
        ),
        patch(
            "free_claude_code.cli.launchers.codex.open_local_request",
            side_effect=URLError("boom"),
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        patch("free_claude_code.cli.launchers.common.register_pid"),
        patch("free_claude_code.cli.launchers.common.unregister_pid"),
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 12345
        process.wait.return_value = 0
        launch(["exec", "hello"])

    assert exc_info.value.code == 0
    command = popen.call_args.args[0]
    assert not any("model_catalog_json=" in arg for arg in command)
    captured = capsys.readouterr()
    assert "could not prepare Codex model catalog" in captured.err
    assert "launching without model picker catalog" in captured.err


def test_pi_launcher_builds_scoped_session_command_and_proxy_env(
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.launchers.pi import (
        build_pi_launcher_command,
        build_pi_launcher_env,
    )

    extension = tmp_path / "pi_extension.ts"
    env = build_pi_launcher_env(
        proxy_root_url="http://127.0.0.1:9191/",
        auth_token=" proxy-token ",
        base_env={
            "PATH": "keep",
            "ANTHROPIC_API_KEY": "native-pi-credential",
            "FCC_PI_API_KEY": "stale-key",
            "FCC_PI_BASE_URL": "https://stale.invalid",
        },
    )

    assert build_pi_launcher_command(
        binary_path="resolved-pi.cmd",
        extension_path=extension,
        argv=["--print", "hello"],
    ) == [
        "resolved-pi.cmd",
        "-e",
        str(extension),
        "--models",
        "free-claude-code/**",
        "--print",
        "hello",
    ]
    assert env == {
        "PATH": "keep",
        "ANTHROPIC_API_KEY": "native-pi-credential",
        "NO_PROXY": "127.0.0.1,localhost,::1",
        "no_proxy": "127.0.0.1,localhost,::1",
        "FCC_PI_BASE_URL": "http://127.0.0.1:9191",
        "FCC_PI_API_KEY": "proxy-token",
    }


def test_pi_launcher_uses_no_auth_sentinel_for_blank_token() -> None:
    from free_claude_code.cli.launchers.pi import build_pi_launcher_env

    env = build_pi_launcher_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="",
        base_env={},
    )

    assert env["FCC_PI_API_KEY"] == "fcc-no-auth"


def test_launch_pi_registers_bundled_extension_for_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.launchers.pi import launch

    monkeypatch.setenv("KEEP_ME", "yes")
    monkeypatch.setenv("FCC_PI_API_KEY", "stale-key")
    extension = tmp_path / "pi_extension.ts"
    extension.write_text("export default () => {};", encoding="utf-8")
    settings = _launcher_settings(port=9191, token="proxy-token")

    with (
        patch("free_claude_code.cli.launchers.pi.get_settings", return_value=settings),
        patch("free_claude_code.cli.launchers.pi.preflight_proxy", return_value=None),
        patch(
            "free_claude_code.cli.launchers.pi.pi_extension_path",
            return_value=extension,
        ),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-pi.cmd",
        ),
        patch(
            "free_claude_code.cli.launchers.pi.pi_binary_is_compatible",
            return_value=True,
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        patch("free_claude_code.cli.launchers.common.register_pid"),
        patch("free_claude_code.cli.launchers.common.unregister_pid"),
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 12345
        process.wait.return_value = 0
        launch(["--print", "hello"])

    assert exc_info.value.code == 0
    assert popen.call_args.args[0] == [
        "resolved-pi.cmd",
        "-e",
        str(extension),
        "--models",
        "free-claude-code/**",
        "--print",
        "hello",
    ]
    child_env = popen.call_args.kwargs["env"]
    assert child_env["FCC_PI_BASE_URL"] == "http://127.0.0.1:9191"
    assert child_env["FCC_PI_API_KEY"] == "proxy-token"
    assert child_env["NO_PROXY"] == "127.0.0.1,localhost,::1"
    assert child_env["no_proxy"] == child_env["NO_PROXY"]
    assert child_env["KEEP_ME"] == "yes"


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["--version"],
        ["config", "set", "theme", "dark"],
        ["install", "npm:example"],
        ["list"],
        ["remove", "npm:example"],
        ["uninstall", "npm:example"],
        ["update"],
    ],
)
def test_launch_pi_passes_management_commands_through_without_proxy(
    argv: list[str],
) -> None:
    from free_claude_code.cli.launchers.pi import launch

    with (
        patch("free_claude_code.cli.launchers.pi.get_settings") as get_settings,
        patch("free_claude_code.cli.launchers.pi.preflight_proxy") as preflight,
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-pi",
        ),
        patch(
            "free_claude_code.cli.launchers.pi.pi_binary_is_compatible",
            return_value=True,
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        patch("free_claude_code.cli.launchers.common.register_pid"),
        patch("free_claude_code.cli.launchers.common.unregister_pid"),
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 12345
        process.wait.return_value = 0
        launch(argv)

    assert exc_info.value.code == 0
    assert popen.call_args.args[0] == ["resolved-pi", *argv]
    get_settings.assert_not_called()
    preflight.assert_not_called()


def test_launch_pi_fails_closed_when_bundled_extension_is_missing(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from free_claude_code.cli.launchers.pi import launch

    settings = _launcher_settings(port=9191)
    with (
        patch("free_claude_code.cli.launchers.pi.get_settings", return_value=settings),
        patch("free_claude_code.cli.launchers.pi.preflight_proxy", return_value=None),
        patch(
            "free_claude_code.cli.launchers.pi.pi_extension_path",
            return_value=tmp_path / "missing.ts",
        ),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-pi",
        ),
        patch(
            "free_claude_code.cli.launchers.pi.pi_binary_is_compatible",
            return_value=True,
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        pytest.raises(SystemExit) as exc_info,
    ):
        launch([])

    assert exc_info.value.code == 1
    popen.assert_not_called()
    assert "bundled Pi extension is missing" in capsys.readouterr().err


def test_pi_install_hints_use_official_platform_installers() -> None:
    from free_claude_code.cli.launchers.pi import pi_install_hint

    assert "https://pi.dev/install.ps1" in pi_install_hint("win32")
    assert "https://pi.dev/install.sh" in pi_install_hint("darwin")


@pytest.mark.parametrize(
    ("help_output", "return_code", "expected"),
    [
        ("--extension <path>\n--models <patterns>\n", 0, True),
        ("--models <patterns>\n", 0, False),
        ("--extension <path>\n", 0, False),
        ("--extension <path>\n--models <patterns>\n", 1, False),
    ],
)
def test_pi_binary_compatibility_requires_both_launcher_capabilities(
    help_output: str,
    return_code: int,
    expected: bool,
) -> None:
    from free_claude_code.cli.launchers.pi import pi_binary_is_compatible

    with patch(
        "free_claude_code.cli.launchers.pi.subprocess.run",
        return_value=SimpleNamespace(returncode=return_code, stdout=help_output),
    ):
        assert pi_binary_is_compatible("resolved-pi") is expected


def test_launch_pi_rejects_unrelated_pi_binary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli.launchers.pi import launch

    with (
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="unrelated-pi",
        ),
        patch(
            "free_claude_code.cli.launchers.pi.pi_binary_is_compatible",
            return_value=False,
        ),
        patch("free_claude_code.cli.launchers.pi.get_settings") as get_settings,
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        pytest.raises(SystemExit) as exc_info,
    ):
        launch([])

    assert exc_info.value.code == 126
    get_settings.assert_not_called()
    popen.assert_not_called()
    captured = capsys.readouterr()
    assert "not a compatible Pi Coding Agent" in captured.err
    assert "https://pi.dev/install." in captured.err


def test_launch_claude_keyboard_interrupt_kills_child_tree() -> None:
    from free_claude_code.cli.launchers.claude import launch

    settings = _launcher_settings(port=9191, token="proxy-token")

    with (
        patch(
            "free_claude_code.cli.launchers.claude.get_settings", return_value=settings
        ),
        patch(
            "free_claude_code.cli.launchers.claude.preflight_proxy", return_value=None
        ),
        patch(
            "free_claude_code.cli.launchers.common.shutil.which",
            return_value="resolved-claude.cmd",
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        patch("free_claude_code.cli.launchers.common.register_pid"),
        patch(
            "free_claude_code.cli.launchers.common.kill_pid_tree_best_effort"
        ) as kill_tree,
        patch("free_claude_code.cli.launchers.common.unregister_pid") as unregister_pid,
        pytest.raises(KeyboardInterrupt),
    ):
        process = popen.return_value
        process.pid = 12345
        process.wait.side_effect = [KeyboardInterrupt, 0]

        launch([])

    kill_tree.assert_called_once_with(12345)
    unregister_pid.assert_called_once_with(12345)


def test_launch_claude_exits_when_command_cannot_be_resolved(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli.launchers.claude import launch

    settings = _launcher_settings()
    with (
        patch(
            "free_claude_code.cli.launchers.claude.get_settings", return_value=settings
        ),
        patch(
            "free_claude_code.cli.launchers.claude.preflight_proxy", return_value=None
        ),
        patch("free_claude_code.cli.launchers.common.shutil.which", return_value=None),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        pytest.raises(SystemExit) as exc_info,
    ):
        launch([])

    assert exc_info.value.code == 127
    popen.assert_not_called()
    captured = capsys.readouterr()
    assert "Could not find Claude Code command: claude" in captured.err
    assert "npm install -g @anthropic-ai/claude-code" in captured.err


def test_launch_claude_unreachable_proxy_exits_with_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli.launchers.claude import launch

    settings = _launcher_settings(port=9393)
    with (
        patch(
            "free_claude_code.cli.launchers.claude.get_settings", return_value=settings
        ),
        patch(
            "free_claude_code.cli.launchers.claude.preflight_proxy",
            return_value="connection refused",
        ),
        patch("free_claude_code.cli.launchers.common.subprocess.Popen") as popen,
        pytest.raises(SystemExit) as exc_info,
    ):
        launch([])

    assert exc_info.value.code == 1
    popen.assert_not_called()
    captured = capsys.readouterr()
    assert "http://127.0.0.1:9393" in captured.err
    assert "fcc-server" in captured.err
