from pathlib import Path
from unittest.mock import patch

import pytest

from free_claude_code.cli import rust_tui
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    return Settings(host="127.0.0.1", port=8082)


def test_native_manifest_is_packaged_under_free_claude_code() -> None:
    path = rust_tui.native_manifest_path()
    assert path.name == "Cargo.toml"
    assert path.parent.name == "native_tui"


def test_configured_native_binary_wins_without_exposing_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "fcc-control-center"
    binary.write_text("native", encoding="utf-8")
    monkeypatch.setenv("FCC_CONTROL_TUI_BINARY", str(binary))

    command = rust_tui.native_control_command(_settings(), notice="startup warning")

    assert command[0] == str(binary)
    assert command[1:3] == ("--base-url", "http://127.0.0.1:8082")
    assert command[3:] == ("--notice", "startup warning")
    assert not any("API_KEY" in part or "TOKEN=" in part for part in command)


def test_source_backed_launcher_uses_packaged_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FCC_CONTROL_TUI_BINARY", raising=False)
    manifest = Path("/tmp/fcc-native/Cargo.toml")
    with (
        patch.object(rust_tui, "native_manifest_path", return_value=manifest),
        patch.object(rust_tui.shutil, "which", side_effect=[None, "/usr/bin/cargo"]),
        patch.object(Path, "is_file", return_value=True),
    ):
        command = rust_tui.native_control_command(_settings())

    assert command[:6] == (
        "/usr/bin/cargo",
        "run",
        "--quiet",
        "--release",
        "--manifest-path",
        str(manifest),
    )
    assert command[-2:] == ("--base-url", "http://127.0.0.1:8082")


def test_missing_native_runtime_fails_with_headless_escape_hatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FCC_CONTROL_TUI_BINARY", raising=False)
    with (
        patch.object(rust_tui.shutil, "which", return_value=None),
        patch.object(Path, "is_file", return_value=False),
        pytest.raises(rust_tui.NativeControlCenterUnavailable) as error,
    ):
        rust_tui.native_control_command(_settings())

    assert "fcc-server --headless" in str(error.value)


def test_native_runner_accepts_normal_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    class Completed:
        returncode = 0

    with (
        patch.object(rust_tui, "native_control_command", return_value=("native",)),
        patch.object(rust_tui.subprocess, "run", return_value=Completed()) as run,
    ):
        rust_tui.run_native_control_center(_settings())

    run.assert_called_once_with(("native",), check=False)


def test_standalone_tui_entrypoint_loads_server_settings() -> None:
    from free_claude_code.cli import commands

    settings = _settings()
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch.object(rust_tui, "run_native_control_center") as run,
    ):
        assert rust_tui.main(()) == 0

    run.assert_called_once_with(settings)
