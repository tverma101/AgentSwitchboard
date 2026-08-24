import os
import stat
import subprocess
import sys

import pytest

from free_claude_code.cli.claude_firewall import (
    CLAUDE_ALLOW_UNCERTIFIED_ENV,
    CLAUDE_KNOWN_GOOD_VERSION_ENV,
    ClaudeCompatibilityError,
    enforce_claude_compatibility,
    ensure_process_wrapper,
    inspect_claude_compatibility,
)


def _fake_claude(tmp_path, output: str) -> str:
    path = tmp_path / "claude"
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
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "256000",
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
