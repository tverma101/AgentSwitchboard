"""Tests for persistent local-scope Claude Computer Use registration."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from free_claude_code.cli import codex_computer_use_registration as registration


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


def _details(python: Path, *, scope: str = "Local") -> str:
    return (
        f"{registration.MCP_SERVER_NAME}:\n"
        f"  Scope: {scope}\n"
        "  Type: stdio\n"
        f"  Command: {python.resolve()}\n"
        f"  Args: -m {registration.MCP_SERVER_MODULE}\n"
    )


def test_ensure_adds_missing_local_registration_then_verifies(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    responses = [
        _completed(1, stderr="No MCP server found with name: fcc-codex-computer-use"),
        _completed(stdout="Added stdio MCP server fcc-codex-computer-use to local config"),
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
    assert payload == {
        "args": ["-m", registration.MCP_SERVER_MODULE],
        "command": str(python.resolve()),
        "type": "stdio",
    }


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
        _completed(stdout="Removed MCP server fcc-codex-computer-use from local config"),
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
    assert env["TERM"] == "dumb"
    assert env["NO_COLOR"] == "1"
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["capture_output"] is True
