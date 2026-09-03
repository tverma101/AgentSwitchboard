import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from free_claude_code.cli.claude_firewall import (
    CLAUDE_ALLOW_UNCERTIFIED_ENV,
    CLAUDE_KNOWN_GOOD_BINARY_ENV,
    CLAUDE_KNOWN_GOOD_VERSION_ENV,
    ClaudeCompatibilityError,
    enforce_claude_compatibility,
    ensure_process_wrapper,
    find_known_good_claude_binary,
    inspect_claude_compatibility,
)
from free_claude_code.core import claude_compatibility


def _fake_claude(tmp_path, output: str) -> str:
    return _fake_claude_at(tmp_path / "claude", output)


def _fake_claude_at(path, output: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' {output!r}\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return str(path)


def test_process_wrapper_is_private_silent_and_reexecs(tmp_path) -> None:
    wrapper = ensure_process_wrapper(tmp_path / "bin" / "wrapper")
    assert wrapper == tmp_path / "bin" / "wrapper"
    assert stat.S_IMODE(wrapper.stat().st_mode) == 0o700
    assert stat.S_IMODE(wrapper.parent.stat().st_mode) & 0o077 == 0
    assert ensure_process_wrapper(wrapper) == wrapper

    environment = {
        **os.environ,
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:8082",
        "ANTHROPIC_AUTH_TOKEN": "fcc-no-auth",
    }
    result = subprocess.run(
        [str(wrapper), sys.executable, "-c", "print('wrapper-ok')"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "wrapper-ok"
    assert result.stderr == ""


def test_process_wrapper_fails_closed_when_proxy_env_is_missing(tmp_path) -> None:
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")
    result = subprocess.run(
        [str(wrapper), sys.executable, "-c", "print('must-not-run')"],
        capture_output=True,
        check=False,
        env={"PATH": os.environ["PATH"]},
        text=True,
    )
    assert result.returncode == 78
    assert result.stdout == ""


def test_legacy_context_wrapper_is_migrated_without_context_variables(tmp_path) -> None:
    wrapper = tmp_path / "wrapper"
    wrapper.write_text(
        """#!/bin/sh
# FCC-generated Claude Code self-spawn firewall. Keep this script silent.
set -eu
: \"${ANTHROPIC_BASE_URL:-}\"
: \"${ANTHROPIC_AUTH_TOKEN:?FCC proxy auth is missing}\"
: \"${CLAUDE_CODE_MAX_CONTEXT_TOKENS:?FCC context cap is missing}\"
: \"${CLAUDE_CODE_AUTO_COMPACT_WINDOW:?FCC auto-compact policy is missing}\"
exec \"$@\"
""",
        encoding="utf-8",
    )
    wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    migrated = ensure_process_wrapper(wrapper)

    assert migrated == wrapper
    body = wrapper.read_text(encoding="utf-8")
    assert "proxy-transport-v2" in body
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in body
    assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in body

    result = subprocess.run(
        [str(wrapper), sys.executable, "-c", "print('migrated-ok')"],
        capture_output=True,
        check=False,
        env={
            "PATH": os.environ["PATH"],
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:8082",
            "ANTHROPIC_AUTH_TOKEN": "fcc-no-auth",
        },
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "migrated-ok"


def test_exact_known_good_version_is_certified(tmp_path) -> None:
    binary = _fake_claude(tmp_path, "2.1.228")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")

    status = inspect_claude_compatibility(
        binary,
        base_env={},
        wrapper_path=wrapper,
    )

    assert status.version == "2.1.228"
    assert status.state == "certified"
    assert status.wrapper_valid is True


def test_new_version_is_quarantined_until_explicit_canary_opt_in(tmp_path) -> None:
    binary = _fake_claude(tmp_path, "2.1.229")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")

    status = inspect_claude_compatibility(
        binary,
        base_env={},
        wrapper_path=wrapper,
    )
    assert status.state == "quarantined"

    with pytest.raises(ClaudeCompatibilityError, match="quarantined"):
        enforce_claude_compatibility(
            binary,
            base_env={},
            wrapper_path=wrapper,
        )

    canary = inspect_claude_compatibility(
        binary,
        base_env={CLAUDE_ALLOW_UNCERTIFIED_ENV: "1"},
        wrapper_path=wrapper,
    )
    assert canary.state == "canary_opt_in"


def test_explicit_known_good_override_is_observable(tmp_path) -> None:
    binary = _fake_claude(tmp_path, "2.1.229 Claude Code")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")
    status = inspect_claude_compatibility(
        binary,
        base_env={CLAUDE_KNOWN_GOOD_VERSION_ENV: "2.1.229"},
        wrapper_path=wrapper,
    )
    assert status.state == "certified"
    assert status.known_good_version == "2.1.229"


def test_find_known_good_binary_requires_an_exact_configured_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        claude_compatibility,
        "_config_dir_path",
        lambda: tmp_path / ".fcc",
    )
    current = _fake_claude(tmp_path / "current", "2.1.250 Claude Code")
    fallback = _fake_claude_at(tmp_path / "fallback" / "claude", "2.1.228 Claude Code")
    wrong_version = _fake_claude_at(
        tmp_path / "wrong" / "claude", "2.1.215 Claude Code"
    )

    base_env = {
        CLAUDE_KNOWN_GOOD_BINARY_ENV: fallback,
        "PATH": str(tmp_path / "wrong"),
    }

    assert (
        find_known_good_claude_binary(
            current,
            base_env=base_env,
            known_good_version="2.1.228",
        )
        == fallback
    )
    assert (
        find_known_good_claude_binary(
            current,
            base_env={"PATH": str(Path(wrong_version).parent)},
            known_good_version="2.1.228",
        )
        is None
    )


def test_install_known_good_binary_is_private_and_offline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        claude_compatibility,
        "_config_dir_path",
        lambda: tmp_path / ".fcc",
    )

    def fake_which(name: str, *, path: str | None = None) -> str:
        del path
        return f"/fake/{name}"

    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        if command[-1] == "--version":
            return subprocess.CompletedProcess(
                command, 0, stdout="2.1.228 Claude Code\n", stderr=""
            )
        if len(command) > 1 and command[1] == "install":
            prefix = Path(command[command.index("--prefix") + 1])
            package = prefix / "node_modules" / "@anthropic-ai" / "claude-code"
            (package / "bin").mkdir(parents=True)
            (package / "install.cjs").write_text("", encoding="utf-8")
            shim = prefix / "node_modules" / ".bin" / "claude"
            shim.parent.mkdir(parents=True)
            shim.write_text("#!/bin/sh\n", encoding="utf-8")
            shim.chmod(0o700)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(claude_compatibility.shutil, "which", fake_which)
    monkeypatch.setattr(claude_compatibility.subprocess, "run", fake_run)

    installed = claude_compatibility.install_known_good_claude_binary(
        base_env={"PATH": "/safe/bin", "ANTHROPIC_AUTH_TOKEN": "must-not-leak"},
        known_good_version="2.1.228",
    )

    assert installed is not None
    assert installed.endswith("/2.1.228/node_modules/.bin/claude")
    assert Path(installed).is_file()
    npm_command = calls[0][0]
    assert "--offline" in npm_command
    assert "--ignore-scripts" in npm_command
    install_env = calls[0][1]["env"]
    assert isinstance(install_env, dict)
    assert "ANTHROPIC_AUTH_TOKEN" not in install_env
