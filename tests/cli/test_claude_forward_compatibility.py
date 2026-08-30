import stat

import pytest

from free_claude_code.cli import claude_firewall
from free_claude_code.cli.claude_firewall import (
    CLAUDE_ALLOW_UNCERTIFIED_ENV,
    CLAUDE_BLOCKED_VERSIONS_ENV,
    CLAUDE_KNOWN_GOOD_VERSION_ENV,
    ensure_process_wrapper,
)


def _fake_claude(tmp_path, version: str) -> str:
    path = tmp_path / "claude"
    path.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {version!r}\n",
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return str(path)


def _managed_env(**extra: str) -> dict[str, str]:
    return {
        CLAUDE_KNOWN_GOOD_VERSION_ENV: "2.1.228",
        **extra,
    }


def _disable_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        claude_firewall,
        "write_compatibility_receipt",
        lambda status: None,
    )


def _enforce(binary, wrapper, env, monkeypatch: pytest.MonkeyPatch):
    _disable_receipt(monkeypatch)
    return claude_firewall.enforce_claude_compatibility(
        binary,
        base_env=env,
        wrapper_path=wrapper,
    )


def test_managed_newer_patch_is_forward_compatible(tmp_path, monkeypatch) -> None:
    binary = _fake_claude(tmp_path, "2.1.229 Claude Code")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")

    status = _enforce(binary, wrapper, _managed_env(), monkeypatch)

    assert status.version == "2.1.229"
    assert status.state == "forward_compatible"
    assert status.known_good_version == "2.1.228"


def test_managed_newer_minor_stays_inside_claude_2x_envelope(
    tmp_path, monkeypatch
) -> None:
    binary = _fake_claude(tmp_path, "2.2.0 Claude Code")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")

    status = _enforce(binary, wrapper, _managed_env(), monkeypatch)

    assert status.state == "forward_compatible"


def test_future_major_requires_explicit_canary(tmp_path, monkeypatch) -> None:
    binary = _fake_claude(tmp_path, "3.0.0 Claude Code")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")
    _disable_receipt(monkeypatch)

    with pytest.raises(claude_firewall.ClaudeCompatibilityError):
        claude_firewall.enforce_claude_compatibility(
            binary,
            base_env=_managed_env(),
            wrapper_path=wrapper,
        )

    canary = _enforce(
        binary,
        wrapper,
        _managed_env(**{CLAUDE_ALLOW_UNCERTIFIED_ENV: "1"}),
        monkeypatch,
    )
    assert canary.state == "canary_opt_in"


def test_known_bad_version_can_be_blocked_without_repinning_every_release(
    tmp_path, monkeypatch
) -> None:
    binary = _fake_claude(tmp_path, "2.1.250 Claude Code")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")
    blocked_env = _managed_env(**{CLAUDE_BLOCKED_VERSIONS_ENV: "2.1.249,2.1.250"})
    _disable_receipt(monkeypatch)

    with pytest.raises(claude_firewall.ClaudeCompatibilityError):
        claude_firewall.enforce_claude_compatibility(
            binary,
            base_env=blocked_env,
            wrapper_path=wrapper,
        )

    canary = _enforce(
        binary,
        wrapper,
        {**blocked_env, CLAUDE_ALLOW_UNCERTIFIED_ENV: "1"},
        monkeypatch,
    )
    assert canary.state == "canary_opt_in"


def test_forward_compatible_version_still_requires_valid_wrapper(
    tmp_path, monkeypatch
) -> None:
    binary = _fake_claude(tmp_path, "2.1.250 Claude Code")
    _disable_receipt(monkeypatch)

    with pytest.raises(claude_firewall.ClaudeCompatibilityError):
        claude_firewall.enforce_claude_compatibility(
            binary,
            base_env=_managed_env(),
            wrapper_path=tmp_path / "missing-wrapper",
        )
