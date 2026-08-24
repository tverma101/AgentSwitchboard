"""Fail-closed Claude Code version and self-spawn compatibility controls."""

import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CLAUDE_PROCESS_WRAPPER_ENV = "CLAUDE_CODE_PROCESS_WRAPPER"
CLAUDE_KNOWN_GOOD_VERSION_ENV = "FCC_CLAUDE_KNOWN_GOOD_VERSION"
CLAUDE_ALLOW_UNCERTIFIED_ENV = "FCC_CLAUDE_ALLOW_UNCERTIFIED"
CLAUDE_PROCESS_WRAPPER_PATH_ENV = "FCC_CLAUDE_PROCESS_WRAPPER_PATH"
DEFAULT_KNOWN_GOOD_CLAUDE_VERSION = "2.1.228"
MIN_PROCESS_WRAPPER_VERSION = (2, 1, 208)
_VERSION_RE = re.compile(r"\b(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)\b")
_WRAPPER_FILENAME = "fcc-claude-process-wrapper"
_RECEIPT_DIRNAME = "claude-compatibility"
_WRAPPER_BODY = """#!/bin/sh
# FCC-generated Claude Code self-spawn firewall. Keep this script silent.
set -eu

case "${ANTHROPIC_BASE_URL:-}" in
  http://127.0.0.1:*|http://localhost:*|http://[::1]:*) ;;
  *) exit 78 ;;
esac

: "${ANTHROPIC_AUTH_TOKEN:?FCC proxy auth is missing}"
: "${CLAUDE_CODE_MAX_CONTEXT_TOKENS:?FCC context cap is missing}"
: "${CLAUDE_CODE_AUTO_COMPACT_WINDOW:?FCC auto-compact policy is missing}"

export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
export DISABLE_AUTOUPDATER=1
export DISABLE_FEEDBACK_COMMAND=1
export DISABLE_ERROR_REPORTING=1
exec "$@"
"""


class ClaudeCompatibilityError(RuntimeError):
    """The installed Claude runtime cannot be safely promoted for FCC use."""


@dataclass(frozen=True, slots=True)
class ClaudeCompatibilityStatus:
    """Sanitized compatibility state for one installed Claude executable."""

    binary_path: str
    version: str | None
    state: str
    known_good_version: str
    wrapper_path: str
    wrapper_valid: bool

    def as_receipt(self) -> dict[str, object]:
        """Return a metadata-only compatibility receipt."""

        return {
            "schema_version": 1,
            "binary_path": self.binary_path,
            "claude_version": self.version,
            "state": self.state,
            "known_good_version": self.known_good_version,
            "process_wrapper_path": self.wrapper_path,
            "process_wrapper_valid": self.wrapper_valid,
            "minimum_wrapper_version": ".".join(
                str(part) for part in MIN_PROCESS_WRAPPER_VERSION
            ),
        }


def _config_dir_path() -> Path:
    """Return FCC's user-private config directory without a package import."""

    return Path.home() / ".fcc"


def default_process_wrapper_path(base_env: Mapping[str, str] | None = None) -> Path:
    """Return the absolute FCC-owned wrapper path."""

    configured = (base_env or os.environ).get(CLAUDE_PROCESS_WRAPPER_PATH_ENV, "")
    if configured.strip():
        return Path(configured).expanduser()
    return _config_dir_path() / "bin" / _WRAPPER_FILENAME


def ensure_process_wrapper(path: Path | None = None) -> Path:
    """Create or validate the silent FCC self-spawn wrapper."""

    wrapper = (path or default_process_wrapper_path()).expanduser()
    if not wrapper.is_absolute():
        raise ClaudeCompatibilityError(
            "FCC Claude process wrapper must use an absolute path"
        )
    if wrapper.exists():
        _validate_process_wrapper(wrapper)
        return wrapper

    try:
        wrapper.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = wrapper.with_name(f".{wrapper.name}.{os.getpid()}.tmp")
        temporary.write_text(_WRAPPER_BODY, encoding="utf-8")
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        temporary.replace(wrapper)
    except OSError as exc:
        raise ClaudeCompatibilityError(
            "FCC could not install its Claude self-spawn wrapper; refusing "
            "to launch an uncontained Claude process"
        ) from exc
    _validate_process_wrapper(wrapper)
    return wrapper


def inspect_claude_compatibility(
    binary_path: str,
    *,
    base_env: Mapping[str, str],
    wrapper_path: Path,
) -> ClaudeCompatibilityStatus:
    """Inspect version and wrapper state without changing certification."""

    known_good = (
        base_env.get(CLAUDE_KNOWN_GOOD_VERSION_ENV, "").strip()
        or DEFAULT_KNOWN_GOOD_CLAUDE_VERSION
    )
    version = _installed_claude_version(binary_path, base_env)
    wrapper_valid = _wrapper_is_valid(wrapper_path)
    if version is None:
        state = "unknown"
    elif (
        version == known_good and _version_tuple(version) >= MIN_PROCESS_WRAPPER_VERSION
    ):
        state = "certified" if wrapper_valid else "quarantined"
    elif _uncertified_opt_in(base_env):
        state = "canary_opt_in" if wrapper_valid else "quarantined"
    else:
        state = "quarantined"
    return ClaudeCompatibilityStatus(
        binary_path=binary_path,
        version=version,
        state=state,
        known_good_version=known_good,
        wrapper_path=str(wrapper_path),
        wrapper_valid=wrapper_valid,
    )


def enforce_claude_compatibility(
    binary_path: str,
    *,
    base_env: Mapping[str, str],
    wrapper_path: Path,
) -> ClaudeCompatibilityStatus:
    """Require certified or explicit canary-opt-in Claude execution."""

    status = inspect_claude_compatibility(
        binary_path,
        base_env=base_env,
        wrapper_path=wrapper_path,
    )
    write_compatibility_receipt(status)
    if status.state not in {"certified", "canary_opt_in"}:
        version = status.version or "unresolved"
        raise ClaudeCompatibilityError(
            "Claude Code version "
            f"{version} is {status.state} for FCC. Known-good="
            f"{status.known_good_version}; run a bounded canary first or set "
            f"{CLAUDE_ALLOW_UNCERTIFIED_ENV}=1 for explicit testing."
        )
    return status


def write_compatibility_receipt(status: ClaudeCompatibilityStatus) -> Path:
    """Persist a sanitized version/wrapper receipt with private permissions."""

    version = status.version or "unknown"
    filename = f"{version.replace('.', '_')}-{status.state}.json"
    directory = _config_dir_path() / _RECEIPT_DIRNAME
    path = directory / filename
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {
            **status.as_receipt(),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temporary.replace(path)
    except OSError as exc:
        raise ClaudeCompatibilityError(
            "FCC could not persist Claude compatibility evidence"
        ) from exc
    return path


def _installed_claude_version(
    binary_path: str,
    base_env: Mapping[str, str],
) -> str | None:
    path = Path(binary_path)
    if not path.is_file():
        return None
    env = dict(base_env)
    env.update(
        {
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_FEEDBACK_COMMAND": "1",
            "DISABLE_ERROR_REPORTING": "1",
        }
    )
    try:
        completed = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            check=False,
            env=env,
            text=True,
            timeout=3.0,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    match = _VERSION_RE.search(f"{completed.stdout}\n{completed.stderr}")
    return match.group(0) if match else None


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        return (0, 0, 0)
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def _uncertified_opt_in(base_env: Mapping[str, str]) -> bool:
    return base_env.get(CLAUDE_ALLOW_UNCERTIFIED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _wrapper_is_valid(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
        body = path.read_text(encoding="utf-8")
    except OSError:
        return False
    required = (
        'exec "$@"',
        '"${ANTHROPIC_BASE_URL:-}"',
        '"${ANTHROPIC_AUTH_TOKEN:?FCC proxy auth is missing}"',
        '"${CLAUDE_CODE_MAX_CONTEXT_TOKENS:?FCC context cap is missing}"',
    )
    return bool(
        stat.S_ISREG(mode)
        and mode & stat.S_IXUSR
        and all(marker in body for marker in required)
    )


def _validate_process_wrapper(path: Path) -> None:
    if not _wrapper_is_valid(path):
        raise ClaudeCompatibilityError(
            f"FCC Claude process wrapper is missing or does not satisfy its "
            f"exec/inherited-environment contract: {path}"
        )


__all__ = [
    "CLAUDE_ALLOW_UNCERTIFIED_ENV",
    "CLAUDE_KNOWN_GOOD_VERSION_ENV",
    "CLAUDE_PROCESS_WRAPPER_ENV",
    "CLAUDE_PROCESS_WRAPPER_PATH_ENV",
    "ClaudeCompatibilityError",
    "ClaudeCompatibilityStatus",
    "default_process_wrapper_path",
    "enforce_claude_compatibility",
    "ensure_process_wrapper",
    "inspect_claude_compatibility",
    "write_compatibility_receipt",
]
