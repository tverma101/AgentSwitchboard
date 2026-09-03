import os
from pathlib import Path
from unittest.mock import patch

import pytest

from free_claude_code.cli import rust_tui
from free_claude_code.config.settings import Settings


@pytest.fixture(autouse=True)
def _standard_server_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep command-shape tests independent of sandbox entry-point tests."""
    monkeypatch.delenv("FCC_SERVER_MODE", raising=False)


def _settings() -> Settings:
    return Settings(host="127.0.0.1", port=8082)


def test_native_manifest_is_packaged_under_free_claude_code() -> None:
    path = rust_tui.native_manifest_path()
    assert path.name == "Cargo.toml"
    assert path.parent.name == "native_tui"


def test_prelaunch_command_passes_private_bootstrap_handoff_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "fcc-control-center"
    binary.write_text("native", encoding="utf-8")
    monkeypatch.setenv("FCC_CONTROL_TUI_BINARY", str(binary))
    state = tmp_path / "state.json"
    result = tmp_path / "result.json"

    command = rust_tui.native_control_command(
        _settings(),
        bootstrap_state=state,
        bootstrap_result=result,
    )

    assert command[-4:] == (
        "--bootstrap-state",
        str(state),
        "--bootstrap-result",
        str(result),
    )


def test_prelaunch_command_requires_both_handoff_paths() -> None:
    with pytest.raises(ValueError, match="provided together"):
        rust_tui.native_control_command(
            _settings(),
            bootstrap_state=Path("/tmp/state.json"),
        )


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
    assert command[3:5] == ("--expected-mode", "standard")
    assert command[5:] == ("--notice", "startup warning")
    assert not any("API_KEY" in part or "TOKEN=" in part for part in command)


def test_source_backed_launcher_uses_packaged_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FCC_CONTROL_TUI_BINARY", raising=False)
    manifest = tmp_path / "fcc-native" / "Cargo.toml"
    manifest.parent.mkdir()
    manifest.write_text('[package]\nname = "fcc-native"\n', encoding="utf-8")
    with (
        patch.object(rust_tui, "native_manifest_path", return_value=manifest),
        patch.object(rust_tui.shutil, "which", side_effect=[None, "/usr/bin/cargo"]),
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
    assert command[-4:] == (
        "--base-url",
        "http://127.0.0.1:8082",
        "--expected-mode",
        "standard",
    )


def test_existing_release_binary_wins_over_cargo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FCC_CONTROL_TUI_BINARY", raising=False)
    manifest = tmp_path / "fcc-native" / "Cargo.toml"
    manifest.parent.mkdir()
    manifest.write_text('[package]\nname = "fcc-native"\n', encoding="utf-8")
    binary = rust_tui.native_release_binary_path(manifest)
    binary.parent.mkdir(parents=True)
    binary.write_text("native", encoding="utf-8")

    with (
        patch.object(rust_tui, "native_manifest_path", return_value=manifest),
        patch.object(rust_tui.shutil, "which", side_effect=[None, "/usr/bin/cargo"]),
    ):
        command = rust_tui.native_control_command(_settings())

    assert command == (
        str(binary),
        "--base-url",
        "http://127.0.0.1:8082",
        "--expected-mode",
        "standard",
    )


def test_stale_release_binary_falls_back_to_cargo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FCC_CONTROL_TUI_BINARY", raising=False)
    manifest = tmp_path / "fcc-native" / "Cargo.toml"
    manifest.parent.mkdir()
    manifest.write_text('[package]\nname = "fcc-native"\n', encoding="utf-8")
    source = manifest.parent / "src" / "main.rs"
    source.parent.mkdir()
    binary = rust_tui.native_release_binary_path(manifest)
    binary.parent.mkdir(parents=True)
    binary.write_text("stale", encoding="utf-8")
    source.write_text("fn main() {}\n", encoding="utf-8")
    os.utime(
        source, ns=(binary.stat().st_atime_ns, binary.stat().st_mtime_ns + 1_000_000)
    )

    with (
        patch.object(rust_tui, "native_manifest_path", return_value=manifest),
        patch.object(rust_tui.shutil, "which", side_effect=[None, "/usr/bin/cargo"]),
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
    assert command[-4:] == (
        "--base-url",
        "http://127.0.0.1:8082",
        "--expected-mode",
        "standard",
    )


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
