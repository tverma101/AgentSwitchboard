import stat

from free_claude_code.cli.claude_firewall import (
    CLAUDE_ALLOW_UNCERTIFIED_ENV,
    CLAUDE_BLOCKED_VERSIONS_ENV,
    CLAUDE_KNOWN_GOOD_VERSION_ENV,
    ensure_process_wrapper,
    inspect_claude_compatibility,
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


def test_managed_newer_patch_is_forward_compatible(tmp_path) -> None:
    binary = _fake_claude(tmp_path, "2.1.229 Claude Code")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")

    status = inspect_claude_compatibility(
        binary,
        base_env=_managed_env(),
        wrapper_path=wrapper,
    )

    assert status.version == "2.1.229"
    assert status.state == "forward_compatible"
    assert status.known_good_version == "2.1.228"


def test_managed_newer_minor_stays_inside_claude_2x_envelope(tmp_path) -> None:
    binary = _fake_claude(tmp_path, "2.2.0 Claude Code")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")

    status = inspect_claude_compatibility(
        binary,
        base_env=_managed_env(),
        wrapper_path=wrapper,
    )

    assert status.state == "forward_compatible"


def test_future_major_requires_explicit_canary(tmp_path) -> None:
    binary = _fake_claude(tmp_path, "3.0.0 Claude Code")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")

    blocked = inspect_claude_compatibility(
        binary,
        base_env=_managed_env(),
        wrapper_path=wrapper,
    )
    canary = inspect_claude_compatibility(
        binary,
        base_env=_managed_env(**{CLAUDE_ALLOW_UNCERTIFIED_ENV: "1"}),
        wrapper_path=wrapper,
    )

    assert blocked.state == "quarantined"
    assert canary.state == "canary_opt_in"


def test_known_bad_version_can_be_blocked_without_repinning_every_release(
    tmp_path,
) -> None:
    binary = _fake_claude(tmp_path, "2.1.250 Claude Code")
    wrapper = ensure_process_wrapper(tmp_path / "wrapper")
    blocked_env = _managed_env(**{CLAUDE_BLOCKED_VERSIONS_ENV: "2.1.249,2.1.250"})

    blocked = inspect_claude_compatibility(
        binary,
        base_env=blocked_env,
        wrapper_path=wrapper,
    )
    canary = inspect_claude_compatibility(
        binary,
        base_env={**blocked_env, CLAUDE_ALLOW_UNCERTIFIED_ENV: "1"},
        wrapper_path=wrapper,
    )

    assert blocked.state == "quarantined"
    assert canary.state == "canary_opt_in"


def test_forward_compatible_version_still_requires_valid_wrapper(tmp_path) -> None:
    binary = _fake_claude(tmp_path, "2.1.250 Claude Code")

    status = inspect_claude_compatibility(
        binary,
        base_env=_managed_env(),
        wrapper_path=tmp_path / "missing-wrapper",
    )

    assert status.state == "quarantined"
    assert status.wrapper_valid is False
