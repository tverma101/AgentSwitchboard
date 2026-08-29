"""Tests for persistent local-scope Claude Computer Use registration."""

import json
import subprocess
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from free_claude_code.cli import codex_computer_use_registration as registration
from free_claude_code.runtime.codex_computer_use import CodexComputerUsePaths


def _completed(
    returncode: int = 0,
    *,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["claude"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _details(
    python: Path,
    *,
    scope: str = "Local",
    command: str | None = None,
    args: str | None = None,
    node: Path | None = None,
    bridge: Path | None = None,
) -> str:
    if node is None and bridge is None:
        current = registration.local_mcp_spec(python_executable=python)
        default_command = current["command"]
        default_args = " ".join(current["args"])
    else:
        default_command = node or python
        default_args = (
            str(bridge)
            if bridge is not None
            else f"-m {registration.MCP_SERVER_MODULE}"
        )
    return (
        f"{registration.MCP_SERVER_NAME}:\n"
        f"  Scope: {scope}\n"
        "  Type: stdio\n"
        f"  Command: {command or default_command}\n"
        f"  Args: {args or default_args}\n"
    )


def _bridge_paths(tmp_path: Path) -> tuple[Path, Path]:
    node = tmp_path / "node"
    bridge = tmp_path / "computer-use-mcp-bridge.mjs"
    node.write_text("", encoding="utf-8")
    bridge.write_text("", encoding="utf-8")
    return node, bridge


def _native_paths(tmp_path: Path) -> tuple[CodexComputerUsePaths, Path]:
    resources = tmp_path / "ChatGPT.app" / "Contents" / "Resources"
    codex = resources / "codex"
    codex.parent.mkdir(parents=True)
    codex.write_text("", encoding="utf-8")
    app = tmp_path / "home" / ".codex" / "computer-use" / "Codex Computer Use.app"
    client = app / "Contents" / "SharedSupport" / "SkyComputerUseClient.app"
    client.mkdir(parents=True)
    paths = CodexComputerUsePaths(
        codex=codex,
        app=app,
        client=client,
    )
    launcher = (
        resources
        / "plugins"
        / "openai-bundled"
        / "plugins"
        / "computer-use"
        / "bin"
        / "computer-use-client-launcher"
    )
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    return paths, launcher


def test_ensure_adds_missing_local_registration_then_verifies(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    responses = [
        _completed(1, stderr="No MCP server found with name: fcc-codex-computer-use"),
        _completed(
            stdout="Added stdio MCP server fcc-codex-computer-use to local config"
        ),
        _completed(stdout=_details(python)),
    ]

    with patch.object(registration, "_run_claude_mcp", side_effect=responses) as run:
        changed = registration.ensure_claude_local_computer_use_mcp(
            claude_binary="/usr/local/bin/claude",
            cwd=tmp_path,
            python_executable=python,
        )

    assert changed is True
    add_argv = run.call_args_list[1].args[0]
    assert add_argv[:5] == [
        "/usr/local/bin/claude",
        "mcp",
        "add-json",
        "--scope",
        "local",
    ]
    assert add_argv[5] == registration.MCP_SERVER_NAME
    payload = json.loads(add_argv[6])
    assert payload == registration.local_mcp_spec(python_executable=python)


@pytest.mark.parametrize(
    "missing_message",
    [
        "No MCP server found with name: fcc-codex-computer-use",
        'No MCP server named "fcc-codex-computer-use". Run `claude mcp add` to add one.',
    ],
)
def test_ensure_treats_claude_missing_server_messages_as_unregistered(
    tmp_path: Path,
    missing_message: str,
) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    responses = [
        _completed(1, stderr=missing_message),
        _completed(
            stdout="Added stdio MCP server fcc-codex-computer-use to local config"
        ),
        _completed(stdout=_details(python)),
    ]

    with patch.object(registration, "_run_claude_mcp", side_effect=responses) as run:
        changed = registration.ensure_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=python,
        )

    assert changed is True
    assert run.call_count == 3


def test_ensure_is_noop_for_exact_owned_local_registration(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")

    with patch.object(
        registration,
        "_run_claude_mcp",
        return_value=_completed(stdout=_details(python)),
    ) as run:
        changed = registration.ensure_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=python,
        )

    assert changed is False
    assert run.call_count == 1


def test_native_mcp_spec_uses_official_bundled_launcher(tmp_path: Path) -> None:
    _paths, launcher = _native_paths(tmp_path)

    spec = registration.native_mcp_spec(launcher)

    assert spec == {
        "type": "stdio",
        "command": str(launcher.resolve()),
        "args": ["mcp"],
    }


def test_ensure_migrates_owned_direct_launcher_to_bridge(tmp_path: Path) -> None:
    _paths, launcher = _native_paths(tmp_path)
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    responses = [
        _completed(
            stdout=_details(
                python,
                command=str(launcher.resolve()),
                args="mcp",
            )
        ),
        _completed(
            stdout="Removed MCP server fcc-codex-computer-use from local config"
        ),
        _completed(
            stdout="Added stdio MCP server fcc-codex-computer-use to local config"
        ),
        _completed(
            stdout=_details(
                python,
            )
        ),
    ]

    with patch.object(registration, "_run_claude_mcp", side_effect=responses) as run:
        changed = registration.ensure_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=python,
            native_launcher=launcher,
        )

    assert changed is True
    payload = json.loads(run.call_args_list[2].args[0][6])
    assert payload == registration.local_mcp_spec(python_executable=python)
    assert run.call_count == 4


def test_ensure_migrates_previous_direct_launcher_to_bridge(
    tmp_path: Path,
) -> None:
    _paths, bundled_launcher = _native_paths(tmp_path)
    profile_launcher = tmp_path / "claude-profile" / "fcc-launcher"
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    responses = [
        _completed(
            stdout=_details(
                python,
                command=str(bundled_launcher.resolve()),
                args="mcp",
            )
        ),
        _completed(
            stdout="Removed MCP server fcc-codex-computer-use from local config"
        ),
        _completed(
            stdout="Added stdio MCP server fcc-codex-computer-use to local config"
        ),
        _completed(
            stdout=_details(
                python,
            )
        ),
    ]

    with patch.object(registration, "_run_claude_mcp", side_effect=responses) as run:
        changed = registration.ensure_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=python,
            native_launcher=profile_launcher,
            legacy_native_launcher=bundled_launcher,
        )

    assert changed is True
    payload = json.loads(run.call_args_list[2].args[0][6])
    assert payload == registration.local_mcp_spec(python_executable=python)


def test_ensure_migrates_resolved_native_launcher_to_bridge(tmp_path: Path) -> None:
    _paths, launcher = _native_paths(tmp_path)
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")

    with patch.object(
        registration,
        "_run_claude_mcp",
        side_effect=[
            _completed(
                stdout=_details(
                    python,
                    command=str(launcher.resolve()),
                    args="mcp",
                )
            ),
            _completed(),
            _completed(),
            _completed(stdout=_details(python)),
        ],
    ) as run:
        changed = registration.ensure_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=python,
            native_launcher=launcher,
        )

    assert changed is True
    assert run.call_count == 4


def test_ensure_migrates_exact_native_launcher_to_bridge(tmp_path: Path) -> None:
    _paths, launcher = _native_paths(tmp_path)
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")

    with patch.object(
        registration,
        "_run_claude_mcp",
        side_effect=[
            _completed(
                stdout=_details(
                    python,
                    command=str(launcher.resolve()),
                    args="mcp",
                )
            ),
            _completed(),
            _completed(),
            _completed(stdout=_details(python)),
        ],
    ) as run:
        changed = registration.ensure_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=python,
            native_launcher=launcher,
        )

    assert changed is True
    assert run.call_count == 4


def test_local_mcp_spec_preserves_uv_tool_symlink_path(tmp_path: Path) -> None:
    target = tmp_path / "base-python"
    target.write_text("", encoding="utf-8")
    tool_python = tmp_path / "tool-python"
    tool_python.symlink_to(target)

    spec = registration.legacy_local_mcp_spec(python_executable=tool_python)

    assert spec["command"] == str(tool_python)
    assert spec["command"] != str(target)


def test_ensure_repairs_exact_owned_legacy_resolved_registration(
    tmp_path: Path,
) -> None:
    target = tmp_path / "base-python"
    target.write_text("", encoding="utf-8")
    tool_python = tmp_path / "tool-python"
    tool_python.symlink_to(target)
    responses = [
        _completed(
            stdout=_details(
                tool_python,
                command=str(target),
                args=f"-m {registration.MCP_SERVER_MODULE}",
            )
        ),
        _completed(
            stdout="Removed MCP server fcc-codex-computer-use from local config"
        ),
        _completed(
            stdout="Added stdio MCP server fcc-codex-computer-use to local config"
        ),
        _completed(stdout=_details(tool_python)),
    ]

    with patch.object(registration, "_run_claude_mcp", side_effect=responses) as run:
        changed = registration.ensure_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=tool_python,
        )

    assert changed is True
    assert run.call_args_list[1].args[0][1:4] == [
        "mcp",
        "remove",
        registration.MCP_SERVER_NAME,
    ]
    payload = json.loads(run.call_args_list[2].args[0][6])
    assert payload == registration.local_mcp_spec(python_executable=tool_python)
    assert run.call_count == 4


def test_ensure_refuses_unrelated_symlink_command(tmp_path: Path) -> None:
    target = tmp_path / "base-python"
    target.write_text("", encoding="utf-8")
    tool_python = tmp_path / "tool-python"
    tool_python.symlink_to(target)
    other = tmp_path / "other-python"
    other.write_text("", encoding="utf-8")

    with (
        patch.object(
            registration,
            "_run_claude_mcp",
            return_value=_completed(stdout=_details(tool_python, command=str(other))),
        ),
        pytest.raises(registration.ClaudeMcpRegistrationError, match="refusing"),
    ):
        registration.ensure_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=tool_python,
        )


def test_ensure_refuses_foreign_or_user_scope_entry(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    foreign = _details(python, scope="User config (available in all your projects)")

    with (
        patch.object(
            registration,
            "_run_claude_mcp",
            return_value=_completed(stdout=foreign),
        ),
        pytest.raises(registration.ClaudeMcpRegistrationError, match="refusing"),
    ):
        registration.ensure_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=python,
        )


def test_remove_only_deletes_exact_owned_local_entry(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    responses = [
        _completed(stdout=_details(python)),
        _completed(
            stdout="Removed MCP server fcc-codex-computer-use from local config"
        ),
    ]

    with patch.object(registration, "_run_claude_mcp", side_effect=responses) as run:
        changed = registration.remove_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=python,
        )

    assert changed is True
    assert run.call_args_list[1].args[0] == [
        "claude",
        "mcp",
        "remove",
        registration.MCP_SERVER_NAME,
        "--scope",
        "local",
    ]


def test_remove_handles_exact_native_launcher(tmp_path: Path) -> None:
    _paths, launcher = _native_paths(tmp_path)
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    responses = [
        _completed(
            stdout=_details(
                python,
                command=str(launcher.resolve()),
                args="mcp",
            )
        ),
        _completed(
            stdout="Removed MCP server fcc-codex-computer-use from local config"
        ),
    ]

    with patch.object(registration, "_run_claude_mcp", side_effect=responses) as run:
        changed = registration.remove_claude_local_computer_use_mcp(
            claude_binary="claude",
            cwd=tmp_path,
            python_executable=python,
            native_launcher=launcher,
        )

    assert changed is True
    assert run.call_count == 2


def test_missing_remove_is_noop(tmp_path: Path) -> None:
    with patch.object(
        registration,
        "_run_claude_mcp",
        return_value=_completed(1, stderr="No MCP server found with name: x"),
    ):
        assert (
            registration.remove_claude_local_computer_use_mcp(
                claude_binary="claude",
                cwd=tmp_path,
            )
            is False
        )


def test_cli_subcommands_are_noninteractive_and_terminal_dumb(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        captured.update(kwargs)
        return _completed(1, stderr="No MCP server found with name: x")

    with patch.object(registration.subprocess, "run", side_effect=fake_run):
        result = registration._run_claude_mcp(
            ["claude", "mcp", "get", registration.MCP_SERVER_NAME],
            cwd=tmp_path,
            base_env={"PATH": "/bin"},
        )

    assert result.returncode == 1
    env = captured["env"]
    assert isinstance(env, dict)
    env = cast(dict[str, str], env)
    assert env["TERM"] == "dumb"
    assert env["NO_COLOR"] == "1"
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["capture_output"] is True
