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

    run.assert_called_once_with(
        settings, notice=None, workspace=None, open=[], line=None
    )


def test_tui_accepts_workspace_file_and_passes_parent_as_notice(
    tmp_path: Path,
) -> None:
    from free_claude_code.cli import commands

    target = tmp_path / "notes.md"
    target.write_text("hello", encoding="utf-8")
    settings = _settings()
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch.object(rust_tui, "run_native_control_center") as run,
    ):
        assert rust_tui.main((str(target),)) == 0

    _, kwargs = run.call_args
    assert kwargs["notice"] is not None
    assert str(tmp_path) in kwargs["notice"]
    assert kwargs["workspace"] == tmp_path
    assert kwargs["open"] == [target]
    assert kwargs["line"] is None


def test_native_command_forwards_workspace_open_and_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "fcc-control-center"
    binary.write_text("native", encoding="utf-8")
    monkeypatch.setenv("FCC_CONTROL_TUI_BINARY", str(binary))
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")

    command = rust_tui.native_control_command(
        _settings(), workspace=tmp_path, open=[target], line=3
    )

    assert command[0] == str(binary)
    assert "--workspace" in command
    assert command[command.index("--workspace") + 1] == str(tmp_path)
    assert "--open" in command
    assert command[command.index("--open") + 1] == str(target)
    assert "--line" in command
    assert command[command.index("--line") + 1] == "3"


def test_native_command_forwards_pending_client_context_without_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "fcc-control-center"
    binary.write_text("native", encoding="utf-8")
    monkeypatch.setenv("FCC_CONTROL_TUI_BINARY", str(binary))

    command = rust_tui.native_control_command(
        _settings(),
        launch_args=("--profile", "coding", "--model", "muse"),
        launch_cwd=tmp_path,
        launch_danger=True,
    )

    assert command[0] == str(binary)
    assert command.count("--launch-arg") == 4
    assert command[command.index("--launch-arg") + 1] == "--profile"
    assert command[command.index("--launch-cwd") + 1] == str(tmp_path)
    assert "--launch-danger" in command
    assert not any("API_KEY" in part or "TOKEN=" in part for part in command)


def test_tui_list_commands_covers_control_center_verbs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert rust_tui.main(("--list-commands",)) == 0
    out = capsys.readouterr().out
    for label in (
        "Toggle page navigation",
        "Toggle status panel",
        "Focus page navigation",
        "Focus page",
    ):
        assert label in out
    for removed in ("Explorer", "Source Control", "Search files", "workbench"):
        assert removed not in out


def test_tui_rejects_missing_workspace(capsys: pytest.CaptureFixture[str]) -> None:
    assert rust_tui.main(("/definitely/not/here-xyz",)) == 2
    assert "does not exist" in capsys.readouterr().err


def test_tui_goto_parses_location(tmp_path: Path) -> None:
    from free_claude_code.cli import commands

    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    settings = _settings()
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch.object(rust_tui, "run_native_control_center") as run,
    ):
        assert rust_tui.main(("--goto", f"{target}:3:7")) == 0

    _, kwargs = run.call_args
    assert f"{target}:3:7" in (kwargs["notice"] or "")
    assert kwargs["workspace"] == tmp_path
    assert kwargs["open"] == [target]
    assert kwargs["line"] == 3


@pytest.mark.parametrize(
    "argv",
    [
        ("--goto", "file-only"),
        ("--goto", "a.py:0:1"),
        ("--goto", "a.py:1:x"),
        ("--diff", "only-one"),
        ("--split", "diagonal"),
        ("--size", "0.5"),
        ("--split", "right", "--size", "0.1"),
        ("--theme", "neon"),
        ("--bogus-flag",),
        ("a", "b"),
    ],
)
def test_tui_rejects_unhonorable_arguments(
    argv: tuple[str, ...], capsys: pytest.CaptureFixture[str]
) -> None:
    assert rust_tui.main(argv) == 2
    assert "Usage:" in capsys.readouterr().err


def test_tui_diff_prints_bounded_preview(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from free_claude_code.cli import commands

    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text("one\ntwo\n", encoding="utf-8")
    after.write_text("one\nthree\n", encoding="utf-8")
    with (
        patch.object(commands, "load_server_settings", return_value=_settings()),
        patch.object(rust_tui, "run_native_control_center"),
    ):
        assert rust_tui.main(("--diff", str(before), str(after))) == 0

    out = capsys.readouterr().out
    assert "-two" in out
    assert "+three" in out


def test_tui_diff_preview_truncates_long_diffs(tmp_path: Path) -> None:
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text("".join(f"line {n}\n" for n in range(200)), encoding="utf-8")
    after.write_text("".join(f"changed {n}\n" for n in range(200)), encoding="utf-8")
    preview = rust_tui.render_diff_preview(before, after, limit=10)
    assert len(preview) == 11
    assert preview[-1].startswith("… truncated")


def test_tui_split_without_tmux_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    assert rust_tui.main(("--split", "right")) == 2
    assert "tmux" in capsys.readouterr().err


def test_tui_split_with_tmux_prints_hint_and_attaches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from free_claude_code.cli import commands

    monkeypatch.setenv("TMUX", "/tmp/tmux-501/default,123,0")
    with (
        patch.object(commands, "load_server_settings", return_value=_settings()),
        patch.object(rust_tui, "run_native_control_center") as run,
    ):
        assert rust_tui.main(("--split", "right", "--size", "0.3")) == 0

    assert "tmux split-window" in capsys.readouterr().out
    run.assert_called_once()


def test_tui_ssh_and_extensions_fail_closed_with_guidance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert rust_tui.main(("--ssh", "user@host")) == 2
    assert "loopback" in capsys.readouterr().err
    assert rust_tui.main(("--install-extension", "some.id")) == 2
    assert "Providers" in capsys.readouterr().err


def test_tui_list_commands_covers_every_page(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert rust_tui.main(("--list-commands",)) == 0
    out = capsys.readouterr().out
    for label in (
        "Dashboard",
        "Providers",
        "Repositories",
        "Models",
        "Routing",
        "Context Window",
        "Local Setup",
        "Settings",
        "Usage",
        "Diagnostics",
    ):
        assert f"Go to {label}" in out


def test_tui_palette_commands_mirror_rust_titles() -> None:
    assert len(rust_tui.PALETTE_COMMANDS) == len(set(rust_tui.PALETTE_COMMANDS))
    assert "Open command palette" in rust_tui.PALETTE_COMMANDS
    assert "Set MODEL to selected model" in rust_tui.PALETTE_COMMANDS
    assert "Choose model provider" in rust_tui.PALETTE_COMMANDS
    assert "Turn focused model on/off" in rust_tui.PALETTE_COMMANDS
    assert "Toggle focused model on/off" not in rust_tui.PALETTE_COMMANDS
    assert "Use repo for next launch" in rust_tui.PALETTE_COMMANDS
    assert "Rescan repositories" in rust_tui.PALETTE_COMMANDS
    assert "Open repo path" in rust_tui.PALETTE_COMMANDS
    assert "Enable selected models" not in rust_tui.PALETTE_COMMANDS
    assert "Disable selected models" not in rust_tui.PALETTE_COMMANDS
    assert "Disable all models" in rust_tui.PALETTE_COMMANDS
    assert "Keyboard shortcuts and help" not in rust_tui.PALETTE_COMMANDS
    assert "Run route diagnostic" in rust_tui.PALETTE_COMMANDS


def test_tui_shortcut_setup_reports_terminal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert rust_tui.main(("--shortcut-setup",)) == 0
    out = capsys.readouterr().out
    assert "Detected terminal:" in out
    assert "Ctrl+K palette" in out


def test_tui_detect_terminal_kind() -> None:
    assert rust_tui.detect_terminal_kind({"KITTY_WINDOW_ID": "1"}) == "kitty"
    assert rust_tui.detect_terminal_kind({"TERM_PROGRAM": "ghostty"}) == "ghostty"
    assert rust_tui.detect_terminal_kind({"ITERM_SESSION_ID": "x"}) == "iterm2"
    assert rust_tui.detect_terminal_kind({"TMUX": "y"}) == "tmux"
    assert rust_tui.detect_terminal_kind({}) == "unknown"


def test_tui_review_rejects_non_git_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rust_tui.main((str(tmp_path), "--review")) == 2
    assert "git" in capsys.readouterr().err.lower()


def test_tui_timing_reports_stages(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import commands

    with (
        patch.object(commands, "load_server_settings", return_value=_settings()),
        patch.object(rust_tui, "run_native_control_center"),
    ):
        assert rust_tui.main(("--timing",)) == 0

    assert "fcc-tui timing:" in capsys.readouterr().err


def test_tui_help_lists_workspace_surface(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert rust_tui.main(("--help",)) == 0
    assert "--goto" in capsys.readouterr().out


def test_tui_build_installs_release_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_BIN_HOME", str(tmp_path))
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text("[package]", encoding="utf-8")
    built = tmp_path / "target" / "release"
    built.mkdir(parents=True)
    (built / "fcc-control-center").write_bytes(b"native")

    class Completed:
        returncode = 0

    with (
        patch.object(rust_tui, "native_manifest_path", return_value=manifest),
        patch.object(rust_tui.shutil, "which", return_value="/usr/bin/cargo"),
        patch.object(rust_tui.subprocess, "run", return_value=Completed()),
    ):
        assert rust_tui.main(("--build",)) == 0

    assert (tmp_path / "fcc-control-center").is_file()
    assert "installed" in capsys.readouterr().out


def test_tui_build_reports_cargo_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_BIN_HOME", str(tmp_path))
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text("[package]", encoding="utf-8")

    class Failed:
        returncode = 1

    with (
        patch.object(rust_tui, "native_manifest_path", return_value=manifest),
        patch.object(rust_tui.shutil, "which", return_value="/usr/bin/cargo"),
        patch.object(rust_tui.subprocess, "run", return_value=Failed()),
    ):
        assert rust_tui.main(("--build",)) == 2

    assert "cargo build" in capsys.readouterr().err
