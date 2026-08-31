"""Persistent Claude local-scope registration for FCC Codex Computer Use."""

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
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


def local_mcp_spec(
    *,
    python_executable: str | Path = sys.executable,
) -> _LocalMcpSpec:
    """Return the app-server-backed stdio server persisted by Claude itself."""

    return {
        "type": "stdio",
        "command": _absolute_path_without_resolving(python_executable),
        "args": ["-m", MCP_SERVER_MODULE],
    }


def legacy_local_mcp_spec(
    *, python_executable: str | Path | None = None
) -> _LocalMcpSpec:
    """Return the historical Python registration for migration compatibility."""

    return local_mcp_spec(python_executable=python_executable or sys.executable)


def native_mcp_spec(launcher: str | Path) -> _LocalMcpSpec:
    """Return a direct native launcher spec kept for migration diagnostics.

    The direct launcher is kept only so old FCC-owned registrations can be
    identified and migrated safely.
    """

    return {
        "type": "stdio",
        "command": _absolute_path_without_resolving(launcher),
        "args": ["mcp"],
    }


def ensure_claude_local_computer_use_mcp(
    *,
    claude_binary: str,
    cwd: str | Path,
    base_env: Mapping[str, str] | None = None,
    python_executable: str | Path | None = None,
    native_launcher: str | Path | None = None,
    legacy_native_launcher: str | Path | None = None,
) -> bool:
    """Ensure Claude uses FCC's app-server-backed Computer Use MCP.

    The Python MCP server owns the Claude-facing boundary and delegates native
    actions through Codex app-server. Native-launcher arguments are accepted
    only as old FCC-owned registration identities for migration.
    """

    expected = local_mcp_spec(
        python_executable=python_executable or sys.executable,
    )
    legacy_candidates: list[_LocalMcpSpec] = []
    if python_executable is not None:
        legacy_candidates.append(
            legacy_local_mcp_spec(python_executable=python_executable)
        )
    if native_launcher is not None:
        legacy_candidates.append(native_mcp_spec(native_launcher))
    if legacy_native_launcher is not None:
        legacy_candidates.append(native_mcp_spec(legacy_native_launcher))
    existing = _get_registration(
        claude_binary=claude_binary,
        cwd=cwd,
        base_env=base_env,
    )
    if existing is not None:
        legacy = _require_owned_registration(
            existing,
            expected,
            legacy_expected=legacy_candidates,
        )
        if not legacy:
            return False
        migration_expected = _migration_expected(
            existing,
            legacy_expected=legacy_candidates,
        )
        _remove_registration(
            claude_binary=claude_binary,
            cwd=cwd,
            base_env=base_env,
        )
        try:
            _add_registration(
                claude_binary=claude_binary,
                cwd=cwd,
                base_env=base_env,
                expected=expected,
            )
        except ClaudeMcpRegistrationError as error:
            _restore_legacy_registration(
                claude_binary=claude_binary,
                cwd=cwd,
                base_env=base_env,
                expected=migration_expected or expected,
                original_error=error,
            )
            raise
        _verify_installed_registration(
            claude_binary=claude_binary,
            cwd=cwd,
            base_env=base_env,
            expected=expected,
        )
        return True

    _add_registration(
        claude_binary=claude_binary,
        cwd=cwd,
        base_env=base_env,
        expected=expected,
    )
    _verify_installed_registration(
        claude_binary=claude_binary,
        cwd=cwd,
        base_env=base_env,
        expected=expected,
    )
    return True


def remove_claude_local_computer_use_mcp(
    *,
    claude_binary: str,
    cwd: str | Path,
    base_env: Mapping[str, str] | None = None,
    python_executable: str | Path | None = None,
    native_launcher: str | Path | None = None,
    legacy_native_launcher: str | Path | None = None,
) -> bool:
    """Remove only the exact FCC-owned local registration for this project."""

    expected = local_mcp_spec(
        python_executable=python_executable or sys.executable,
    )
    legacy_candidates: list[_LocalMcpSpec] = []
    if python_executable is not None:
        legacy_candidates.append(
            legacy_local_mcp_spec(python_executable=python_executable)
        )
    if native_launcher is not None:
        legacy_candidates.append(native_mcp_spec(native_launcher))
    if legacy_native_launcher is not None:
        legacy_candidates.append(native_mcp_spec(legacy_native_launcher))
    existing = _get_registration(
        claude_binary=claude_binary,
        cwd=cwd,
        base_env=base_env,
    )
    if existing is None:
        return False
    _require_owned_registration(
        existing,
        expected,
        legacy_expected=legacy_candidates,
    )

    _remove_registration(
        claude_binary=claude_binary,
        cwd=cwd,
        base_env=base_env,
    )
    return True


def _add_registration(
    *,
    claude_binary: str,
    cwd: str | Path,
    base_env: Mapping[str, str] | None,
    expected: _LocalMcpSpec,
) -> None:
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


def _remove_registration(
    *,
    claude_binary: str,
    cwd: str | Path,
    base_env: Mapping[str, str] | None,
) -> None:
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


def _verify_installed_registration(
    *,
    claude_binary: str,
    cwd: str | Path,
    base_env: Mapping[str, str] | None,
    expected: _LocalMcpSpec,
) -> None:
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


def _restore_legacy_registration(
    *,
    claude_binary: str,
    cwd: str | Path,
    base_env: Mapping[str, str] | None,
    expected: _LocalMcpSpec,
    original_error: ClaudeMcpRegistrationError,
) -> None:
    legacy: _LocalMcpSpec = {
        "type": expected["type"],
        "command": _resolved_path(expected["command"]),
        "args": list(expected["args"]),
    }
    try:
        _add_registration(
            claude_binary=claude_binary,
            cwd=cwd,
            base_env=base_env,
            expected=legacy,
        )
    except ClaudeMcpRegistrationError as restore_error:
        raise ClaudeMcpRegistrationError(
            f"{original_error}; FCC could not restore the previous legacy "
            f"registration: {restore_error}"
        ) from original_error


def _absolute_path_without_resolving(path: str | Path) -> str:
    """Normalize an executable path while preserving symlink identity."""

    expanded = os.path.expanduser(os.fspath(path))
    return os.path.abspath(expanded)


def _resolved_path(path: str | Path) -> str:
    """Return the old registration form for narrowly-scoped migration."""

    return str(Path(path).expanduser().resolve())


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
        normalized = combined.casefold()
        if "no mcp server" in normalized and (
            "found" in normalized or "named" in normalized
        ):
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
    *,
    legacy_expected: Sequence[_LocalMcpSpec] = (),
) -> bool:
    if _registration_matches(actual, expected, allow_resolved=False):
        return False
    if _registration_matches(actual, expected, allow_resolved=True):
        return True
    if (
        _migration_expected(
            actual,
            legacy_expected=legacy_expected,
        )
        is not None
    ):
        return True
    raise ClaudeMcpRegistrationError(
        f"Claude MCP name {MCP_SERVER_NAME!r} already exists but is not "
        "the exact FCC-owned local Computer Use server; refusing to overwrite it"
    )


def _migration_expected(
    actual: Mapping[str, str],
    *,
    legacy_expected: Sequence[_LocalMcpSpec],
) -> _LocalMcpSpec | None:
    for candidate in legacy_expected:
        if _registration_matches(actual, candidate, allow_resolved=True):
            return candidate
    return None


def _registration_matches(
    actual: Mapping[str, str],
    expected: _LocalMcpSpec,
    *,
    allow_resolved: bool,
) -> bool:
    expected_args = " ".join(expected["args"])
    scope = actual.get("scope", "")
    if not (
        scope.casefold().startswith("local")
        and actual.get("type", "").casefold() == "stdio"
        and actual.get("args") == expected_args
    ):
        return False
    command = actual.get("command")
    if command == expected["command"]:
        return True
    return allow_resolved and command == _resolved_path(expected["command"])


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
    "legacy_local_mcp_spec",
    "local_mcp_spec",
    "native_mcp_spec",
    "remove_claude_local_computer_use_mcp",
]
