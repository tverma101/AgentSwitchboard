"""Persistent Claude local-scope registration for FCC Codex Computer Use."""

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

MCP_SERVER_NAME = "fcc-codex-computer-use"
MCP_SERVER_MODULE = "free_claude_code.cli.codex_computer_use_mcp"
MCP_COMMAND_TIMEOUT_SECONDS = 20.0


class _LocalMcpSpec(TypedDict):
    type: str
    command: str
    args: list[str]


class ClaudeMcpRegistrationError(RuntimeError):
    """Raised when FCC cannot safely own its namespaced Claude MCP entry."""


def local_mcp_spec(*, python_executable: str | Path = sys.executable) -> _LocalMcpSpec:
    """Return the deterministic stdio server config persisted by Claude itself."""

    executable = str(Path(python_executable).expanduser().resolve())
    return {
        "type": "stdio",
        "command": executable,
        "args": ["-m", MCP_SERVER_MODULE],
    }


def ensure_claude_local_computer_use_mcp(
    *,
    claude_binary: str,
    cwd: str | Path,
    base_env: Mapping[str, str] | None = None,
    python_executable: str | Path = sys.executable,
) -> bool:
    """Ensure the current project has exactly FCC's private local MCP entry."""

    expected = local_mcp_spec(python_executable=python_executable)
    existing = _get_registration(
        claude_binary=claude_binary,
        cwd=cwd,
        base_env=base_env,
    )
    if existing is not None:
        _require_owned_registration(existing, expected)
        return False

    encoded = json.dumps(
        expected,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    result = _run_claude_mcp(
        [
            claude_binary,
            "mcp",
            "add-json",
            "--scope",
            "local",
            MCP_SERVER_NAME,
            encoded,
        ],
        cwd=cwd,
        base_env=base_env,
    )
    if result.returncode != 0:
        raise ClaudeMcpRegistrationError(
            "Claude failed to add the FCC Computer Use MCP server: "
            + _safe_subprocess_detail(result)
        )

    installed = _get_registration(
        claude_binary=claude_binary,
        cwd=cwd,
        base_env=base_env,
    )
    if installed is None:
        raise ClaudeMcpRegistrationError(
            "Claude reported MCP registration success but the local entry is absent"
        )
    _require_owned_registration(installed, expected)
    return True


def remove_claude_local_computer_use_mcp(
    *,
    claude_binary: str,
    cwd: str | Path,
    base_env: Mapping[str, str] | None = None,
    python_executable: str | Path = sys.executable,
) -> bool:
    """Remove only the exact FCC-owned local registration for this project."""

    expected = local_mcp_spec(python_executable=python_executable)
    existing = _get_registration(
        claude_binary=claude_binary,
        cwd=cwd,
        base_env=base_env,
    )
    if existing is None:
        return False
    _require_owned_registration(existing, expected)

    result = _run_claude_mcp(
        [
            claude_binary,
            "mcp",
            "remove",
            MCP_SERVER_NAME,
            "--scope",
            "local",
        ],
        cwd=cwd,
        base_env=base_env,
    )
    if result.returncode != 0:
        raise ClaudeMcpRegistrationError(
            "Claude failed to remove the FCC Computer Use MCP server: "
            + _safe_subprocess_detail(result)
        )
    return True


def _get_registration(
    *,
    claude_binary: str,
    cwd: str | Path,
    base_env: Mapping[str, str] | None,
) -> dict[str, str] | None:
    result = _run_claude_mcp(
        [claude_binary, "mcp", "get", MCP_SERVER_NAME],
        cwd=cwd,
        base_env=base_env,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        if "No MCP server found" in combined:
            return None
        raise ClaudeMcpRegistrationError(
            "Claude could not inspect the FCC Computer Use MCP registration: "
            + _safe_subprocess_detail(result)
        )

    fields: dict[str, str] = {}
    for raw in result.stdout.splitlines():
        line = raw.strip()
        for key in ("Scope", "Type", "Command", "Args"):
            prefix = f"{key}:"
            if line.startswith(prefix):
                fields[key.lower()] = line[len(prefix) :].strip()
                break
    required = {"scope", "type", "command", "args"}
    if not required.issubset(fields):
        raise ClaudeMcpRegistrationError(
            "Claude returned an unrecognized MCP detail format for the FCC entry"
        )
    return fields


def _require_owned_registration(
    actual: Mapping[str, str],
    expected: _LocalMcpSpec,
) -> None:
    expected_args = " ".join(expected["args"])
    scope = actual.get("scope", "")
    matches = (
        scope.casefold().startswith("local")
        and actual.get("type", "").casefold() == "stdio"
        and actual.get("command") == expected["command"]
        and actual.get("args") == expected_args
    )
    if not matches:
        raise ClaudeMcpRegistrationError(
            f"Claude MCP name {MCP_SERVER_NAME!r} already exists but is not "
            "the exact FCC-owned local Computer Use server; refusing to overwrite it"
        )


def _run_claude_mcp(
    argv: list[str],
    *,
    cwd: str | Path,
    base_env: Mapping[str, str] | None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ if base_env is None else base_env)
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    return subprocess.run(
        argv,
        cwd=str(Path(cwd).expanduser()),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=MCP_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )


def _safe_subprocess_detail(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stderr or result.stdout).strip().replace("\n", " ")
    if not text:
        return f"exit {result.returncode}"
    return text[:500]


__all__ = [
    "MCP_SERVER_MODULE",
    "MCP_SERVER_NAME",
    "ClaudeMcpRegistrationError",
    "ensure_claude_local_computer_use_mcp",
    "local_mcp_spec",
    "remove_claude_local_computer_use_mcp",
]
