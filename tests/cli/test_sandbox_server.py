"""Tests for the sandboxed `t-fcc-server` entry point and state-dir redirect."""

import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from free_claude_code.cli.entrypoints import (
    SANDBOX_PORT_DEFAULT,
    _apply_sandbox_defaults,
    _seed_sandbox_env,
)
from free_claude_code.config.paths import FCC_CONFIG_DIR_ENV, config_dir_path


def test_config_dir_path_defaults_to_home_fcc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an override the config directory stays at ~/.fcc."""
    monkeypatch.delenv(FCC_CONFIG_DIR_ENV, raising=False)
    assert config_dir_path() == Path.home() / ".fcc"


def test_config_dir_path_honors_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """FCC_CONFIG_DIR redirects every derived path away from ~/.fcc."""
    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, str(tmp_path / "redirected"))
    assert config_dir_path() == tmp_path / "redirected"
    assert config_dir_path() / ".env" == tmp_path / "redirected" / ".env"


def test_config_dir_path_blank_override_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank override string must not redirect to an empty relative path."""
    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, "   ")
    assert config_dir_path() == Path.home() / ".fcc"


def test_apply_sandbox_defaults_sets_state_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sandbox startup points FCC state at ~/.fcc-sandbox and port 8083."""
    # _apply_sandbox_defaults writes os.environ directly. monkeypatch.delenv on
    # an absent key records nothing, so prime each key with setenv (records the
    # old value for teardown) and delete it so the function sees "absent".
    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, "")
    del os.environ[FCC_CONFIG_DIR_ENV]
    monkeypatch.setenv("PORT", "")
    del os.environ["PORT"]
    monkeypatch.setenv("FCC_SERVER_MODE", "")
    monkeypatch.setattr(Path, "home", lambda: Path("/tmp/fcc-sandbox-home"))

    _apply_sandbox_defaults()

    assert os.environ[FCC_CONFIG_DIR_ENV] == "/tmp/fcc-sandbox-home/.fcc-sandbox"
    assert os.environ["PORT"] == str(SANDBOX_PORT_DEFAULT)
    assert os.environ["ENABLE_WEB_SERVER_TOOLS"] == "true"
    assert os.environ["ENABLE_LOCAL_A3S_SEARCH"] == "true"


def test_sandbox_defaults_are_applied_before_settings_import(tmp_path: Path) -> None:
    """Sandbox settings must resolve env files beneath the sandbox directory."""
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    (sandbox_dir / ".env").write_text(
        "ANTHROPIC_AUTH_TOKEN=sandbox-only-token\n", encoding="utf-8"
    )
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "FCC_CONFIG_DIR",
            "FCC_ENV_FILE",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY",
        }
    }
    child_env[FCC_CONFIG_DIR_ENV] = str(sandbox_dir)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from free_claude_code.cli import entrypoints; "
                "entrypoints._apply_sandbox_defaults(); "
                "from free_claude_code.config.settings import Settings; "
                "print(Settings.model_config['env_file'][-1]); "
                "print(Settings().anthropic_auth_token)"
            ),
        ],
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(sandbox_dir / ".env"),
        "sandbox-only-token",
    ]


def test_apply_sandbox_defaults_preserves_explicit_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit PORT choice is never clobbered by the sandbox default."""
    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, "")
    del os.environ[FCC_CONFIG_DIR_ENV]
    monkeypatch.setenv("PORT", "9099")
    monkeypatch.setenv("FCC_SERVER_MODE", "")
    monkeypatch.setattr(Path, "home", lambda: Path("/tmp/fcc-sandbox-home"))

    _apply_sandbox_defaults()

    assert os.environ["PORT"] == "9099"


def test_apply_sandbox_defaults_preserves_explicit_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An explicit FCC_CONFIG_DIR takes precedence over sandbox convenience vars."""
    configured = tmp_path / "configured"
    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, str(configured))
    monkeypatch.setenv("FCC_SANDBOX_DIR", str(tmp_path / "sandbox"))
    monkeypatch.setenv("PORT", "")
    del os.environ["PORT"]
    monkeypatch.setenv("FCC_SERVER_MODE", "")

    _apply_sandbox_defaults()

    assert config_dir_path() == configured
    assert os.environ[FCC_CONFIG_DIR_ENV] == str(configured)


def test_sandbox_banner_uses_resolved_admin_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sandbox startup identifies its state directory and actual admin URL."""
    from free_claude_code.cli import commands, entrypoints

    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, str(tmp_path / "state"))
    monkeypatch.setenv("PORT", "9191")
    monkeypatch.setenv("FCC_SERVER_MODE", "")
    settings = type("SettingsStub", (), {"host": "0.0.0.0", "port": 9191})()

    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch.object(entrypoints, "_run_server_entrypoint") as run_server,
        patch.object(entrypoints, "set_process_identity") as set_identity,
    ):
        entrypoints.serve_sandbox(("--headless",))

    output = capsys.readouterr().out
    assert str(tmp_path / "state") in output
    assert "http://127.0.0.1:9191/admin" in output
    run_server.assert_called_once_with(headless=True)
    set_identity.assert_called_once_with("Server", "sandbox")


def test_apply_sandbox_defaults_honors_sandbox_dir_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """FCC_SANDBOX_DIR moves the sandbox state root."""
    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, "")
    del os.environ[FCC_CONFIG_DIR_ENV]
    monkeypatch.setenv("FCC_SANDBOX_DIR", str(tmp_path / "custom"))
    monkeypatch.setenv("PORT", "")
    del os.environ["PORT"]
    monkeypatch.setenv("FCC_SERVER_MODE", "")
    monkeypatch.setattr(Path, "home", lambda: Path(tmp_path))

    _apply_sandbox_defaults()

    assert os.environ[FCC_CONFIG_DIR_ENV] == str(tmp_path / "custom")
    assert config_dir_path() == tmp_path / "custom"


def test_seed_sandbox_env_copies_live_env_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """First-run seeding copies the live env with owner-only permissions."""
    live_env = tmp_path / "live" / ".fcc" / ".env"
    live_env.parent.mkdir(parents=True)
    live_env.write_text("MODEL=nvidia_nim/test\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "live")

    sandbox_dir = tmp_path / "sandbox"
    _seed_sandbox_env(sandbox_dir)

    sandbox_env = sandbox_dir / ".env"
    assert sandbox_env.read_text("utf-8") == "MODEL=nvidia_nim/test\n"
    assert stat.S_IMODE(sandbox_env.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


def test_seed_sandbox_env_never_overwrites(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An existing sandbox env wins over the live copy."""
    live_env = tmp_path / "live" / ".fcc" / ".env"
    live_env.parent.mkdir(parents=True)
    live_env.write_text("MODEL=nvidia_nim/live\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "live")

    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    existing = sandbox_dir / ".env"
    existing.write_text("MODEL=nvidia_nim/sandbox\n", encoding="utf-8")

    _seed_sandbox_env(sandbox_dir)

    assert existing.read_text("utf-8") == "MODEL=nvidia_nim/sandbox\n"


def test_seed_sandbox_env_skips_without_live_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No live env means the sandbox simply starts unseeded."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "live")

    sandbox_dir = tmp_path / "sandbox"
    _seed_sandbox_env(sandbox_dir)

    assert not (sandbox_dir / ".env").exists()


def test_pyproject_registers_sandbox_entry_point() -> None:
    """The sandbox server is an installed console script."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject.open("rb") as handle:
        scripts = tomllib.load(handle)["project"]["scripts"]

    assert scripts["t-fcc-server"] == "free_claude_code.cli.entrypoints:serve_sandbox"
    assert scripts["fcc-server"] == "free_claude_code.cli.entrypoints:serve"


def test_learning_home_follows_config_dir_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Learning profiles land inside the redirected state root."""
    from free_claude_code.learning.config import learning_home

    monkeypatch.delenv("FCC_LEARNING_HOME", raising=False)
    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, str(tmp_path / "state"))

    assert learning_home() == tmp_path / "state" / "learning"


def test_context_governor_default_follows_config_dir_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Context artifacts land inside the redirected state root."""
    from free_claude_code.core.anthropic.context_governor import (
        ContextGovernorConfig,
    )

    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, str(tmp_path / "state"))

    config = ContextGovernorConfig()
    assert config.artifact_dir == tmp_path / "state" / "context-artifacts"


def test_claude_compatibility_config_dir_honors_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The compatibility layer's local helper respects FCC_CONFIG_DIR."""
    from free_claude_code.core.claude_compatibility import (
        default_process_wrapper_path,
    )

    monkeypatch.setenv(FCC_CONFIG_DIR_ENV, str(tmp_path / "state"))
    monkeypatch.delenv("FCC_CLAUDE_PROCESS_WRAPPER_PATH", raising=False)

    with patch.dict(os.environ):
        wrapper = default_process_wrapper_path({})

    assert wrapper == tmp_path / "state" / "bin" / "fcc-claude-process-wrapper"
