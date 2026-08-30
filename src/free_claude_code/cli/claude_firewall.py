"""CLI facade for FCC's shared Claude compatibility controls.

The core module owns the exact known-good rollback machinery. This facade adds a
narrow forward-compatibility policy for normal CLI launches: newer Claude 2.x
clients are admitted while the established process-wrapper contract still
holds, unless a version is explicitly blocked. Provider/protocol drift remains
fail-loud in the existing conversion layers instead of being guessed from a
patch-version change alone.
"""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from free_claude_code.core import claude_compatibility as _core

CLAUDE_ALLOW_UNCERTIFIED_ENV = _core.CLAUDE_ALLOW_UNCERTIFIED_ENV
CLAUDE_KNOWN_GOOD_BINARY_ENV = _core.CLAUDE_KNOWN_GOOD_BINARY_ENV
CLAUDE_KNOWN_GOOD_VERSION_ENV = _core.CLAUDE_KNOWN_GOOD_VERSION_ENV
CLAUDE_PROCESS_WRAPPER_ENV = _core.CLAUDE_PROCESS_WRAPPER_ENV
CLAUDE_PROCESS_WRAPPER_PATH_ENV = _core.CLAUDE_PROCESS_WRAPPER_PATH_ENV
CLAUDE_BLOCKED_VERSIONS_ENV = "FCC_CLAUDE_BLOCKED_VERSIONS"

ClaudeCompatibilityError = _core.ClaudeCompatibilityError
ClaudeCompatibilityStatus = _core.ClaudeCompatibilityStatus

default_process_wrapper_path = _core.default_process_wrapper_path
ensure_process_wrapper = _core.ensure_process_wrapper
find_known_good_claude_binary = _core.find_known_good_claude_binary
install_known_good_claude_binary = _core.install_known_good_claude_binary
write_compatibility_receipt = _core.write_compatibility_receipt


def inspect_claude_compatibility(
    binary_path: str,
    *,
    base_env: Mapping[str, str],
    wrapper_path: Path,
) -> ClaudeCompatibilityStatus:
    """Inspect Claude using exact rollback state plus bounded forward admission."""

    status = _core.inspect_claude_compatibility(
        binary_path,
        base_env=base_env,
        wrapper_path=wrapper_path,
    )
    version = status.version
    if version is None or not status.wrapper_valid:
        return status
    if version == status.known_good_version:
        return status

    installed = _version_tuple(version)
    known_good = _version_tuple(status.known_good_version)
    if installed == (0, 0, 0) or known_good == (0, 0, 0):
        return status

    explicitly_allowed = _uncertified_opt_in(base_env)
    if version in _blocked_versions(base_env):
        return replace(
            status,
            state="canary_opt_in" if explicitly_allowed else "quarantined",
        )

    if (
        installed[0] == known_good[0] == 2
        and installed > known_good
        and installed >= _core.MIN_PROCESS_WRAPPER_VERSION
    ):
        return replace(status, state="forward_compatible")
    return status


def enforce_claude_compatibility(
    binary_path: str,
    *,
    base_env: Mapping[str, str],
    wrapper_path: Path,
) -> ClaudeCompatibilityStatus:
    """Allow known-good, forward-compatible 2.x, or explicit canary execution."""

    status = inspect_claude_compatibility(
        binary_path,
        base_env=base_env,
        wrapper_path=wrapper_path,
    )
    write_compatibility_receipt(status)
    if status.state not in {"certified", "forward_compatible", "canary_opt_in"}:
        version = status.version or "unresolved"
        raise ClaudeCompatibilityError(
            "Claude Code version "
            f"{version} is {status.state} for FCC. Known-good="
            f"{status.known_good_version}; newer compatible Claude 2.x releases "
            "are admitted automatically, while older, blocked, structurally "
            "unsupported, and future-major clients require an explicit canary. "
            f"Set {_core.CLAUDE_ALLOW_UNCERTIFIED_ENV}=1 only for bounded testing."
        )
    return status


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.strip().split(".")
    if len(parts) != 3:
        return (0, 0, 0)
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return (0, 0, 0)


def _blocked_versions(base_env: Mapping[str, str]) -> frozenset[str]:
    raw = base_env.get(CLAUDE_BLOCKED_VERSIONS_ENV, "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _uncertified_opt_in(base_env: Mapping[str, str]) -> bool:
    return base_env.get(CLAUDE_ALLOW_UNCERTIFIED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


__all__ = [
    "CLAUDE_ALLOW_UNCERTIFIED_ENV",
    "CLAUDE_BLOCKED_VERSIONS_ENV",
    "CLAUDE_KNOWN_GOOD_BINARY_ENV",
    "CLAUDE_KNOWN_GOOD_VERSION_ENV",
    "CLAUDE_PROCESS_WRAPPER_ENV",
    "CLAUDE_PROCESS_WRAPPER_PATH_ENV",
    "ClaudeCompatibilityError",
    "ClaudeCompatibilityStatus",
    "default_process_wrapper_path",
    "enforce_claude_compatibility",
    "ensure_process_wrapper",
    "find_known_good_claude_binary",
    "inspect_claude_compatibility",
    "install_known_good_claude_binary",
    "write_compatibility_receipt",
]
