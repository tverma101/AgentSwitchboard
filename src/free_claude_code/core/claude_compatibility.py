"""Fail-closed Claude Code version and self-spawn compatibility controls."""

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CLAUDE_PROCESS_WRAPPER_ENV = "CLAUDE_CODE_PROCESS_WRAPPER"
CLAUDE_KNOWN_GOOD_VERSION_ENV = "FCC_CLAUDE_KNOWN_GOOD_VERSION"
CLAUDE_KNOWN_GOOD_BINARY_ENV = "FCC_CLAUDE_KNOWN_GOOD_BINARY"
CLAUDE_ALLOW_UNCERTIFIED_ENV = "FCC_CLAUDE_ALLOW_UNCERTIFIED"
CLAUDE_PROCESS_WRAPPER_PATH_ENV = "FCC_CLAUDE_PROCESS_WRAPPER_PATH"
DEFAULT_KNOWN_GOOD_CLAUDE_VERSION = "2.1.228"
MIN_PROCESS_WRAPPER_VERSION = (2, 1, 208)
_VERSION_RE = re.compile(r"\b(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)\b")
_CLAUDE_PACKAGE_NAME = "@anthropic-ai/claude-code"
_CLAUDE_INSTALL_ROOT_NAME = "claude-code"
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


def find_known_good_claude_binary(
    current_binary_path: str,
    *,
    base_env: Mapping[str, str],
    known_good_version: str | None = None,
) -> str | None:
    """Find a locally installed Claude executable with the exact known-good version.

    Candidate paths are deliberately bounded to an explicitly configured path,
    ``PATH`` entries, and FCC's own versioned install directory.  A filename or
    package directory is never trusted without executing ``--version`` and
    matching the exact expected version.
    """

    expected_version = _known_good_version(known_good_version, base_env)
    if expected_version is None:
        return None

    current_path = os.path.realpath(os.path.abspath(current_binary_path))
    candidates: list[Path] = []
    configured = base_env.get(CLAUDE_KNOWN_GOOD_BINARY_ENV, "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    candidates.extend(
        Path(directory).expanduser() / "claude"
        for directory in os.get_exec_path(dict(base_env))
    )

    install_root = _config_dir_path() / _CLAUDE_INSTALL_ROOT_NAME / expected_version
    candidates.extend(
        (
            install_root / "node_modules" / ".bin" / "claude",
            install_root / "node_modules" / _CLAUDE_PACKAGE_NAME / "bin" / "claude.exe",
            install_root / "bin" / "claude",
        )
    )

    seen: set[str] = set()
    for candidate in candidates:
        candidate_path = Path(os.path.abspath(os.fspath(candidate)))
        candidate_key = os.path.realpath(os.fspath(candidate_path))
        if candidate_key in seen or candidate_key == current_path:
            continue
        seen.add(candidate_key)
        if not candidate_path.is_file():
            continue
        if _installed_claude_version(str(candidate_path), base_env) == expected_version:
            return str(candidate_path)
    return None


def install_known_good_claude_binary(
    *,
    base_env: Mapping[str, str],
    known_good_version: str,
) -> str | None:
    """Install an exact known-good Claude version from npm's offline cache.

    This is a private, versioned FCC install and never changes the user's
    global ``claude`` command.  npm lifecycle scripts remain disabled; Claude's
    official native-binary installer is invoked explicitly after dependencies
    are unpacked.  If the exact package is not already cached, the bounded
    offline install fails without contacting the network.
    """

    expected_version = _known_good_version(known_good_version, base_env)
    if expected_version is None:
        return None
    path_env = base_env.get("PATH", os.defpath)
    npm = shutil.which("npm", path=path_env)
    node = shutil.which("node", path=path_env)
    if npm is None or node is None:
        return None

    install_parent = _config_dir_path() / _CLAUDE_INSTALL_ROOT_NAME
    try:
        install_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{expected_version}-repair-",
                dir=str(install_parent),
            )
        )
    except OSError:
        return None

    preserve_staging = False
    install_env = _offline_node_environment(base_env)
    package_spec = f"{_CLAUDE_PACKAGE_NAME}@{expected_version}"
    try:
        result = subprocess.run(
            [
                npm,
                "install",
                "--prefix",
                str(staging),
                "--offline",
                "--no-audit",
                "--no-fund",
                "--ignore-scripts",
                package_spec,
            ],
            capture_output=True,
            check=False,
            cwd=str(staging),
            env=install_env,
            text=True,
            timeout=60.0,
        )
        if result.returncode != 0:
            return None

        native_installer = (
            staging / "node_modules" / _CLAUDE_PACKAGE_NAME / "install.cjs"
        )
        if not native_installer.is_file():
            return None
        result = subprocess.run(
            [node, str(native_installer)],
            capture_output=True,
            check=False,
            cwd=str(staging),
            env=install_env,
            text=True,
            timeout=30.0,
        )
        if result.returncode != 0:
            return None

        staged_binary = staging / "node_modules" / ".bin" / "claude"
        if _installed_claude_version(str(staged_binary), base_env) != expected_version:
            return None

        stable_root = install_parent / expected_version
        if not os.path.lexists(stable_root):
            try:
                staging.replace(stable_root)
            except OSError:
                return None
            preserve_staging = True
            return str(stable_root / "node_modules" / ".bin" / "claude")

        # Never overwrite a pre-existing user directory.  The private staging
        # directory is still a valid exact-version fallback for this launch.
        preserve_staging = True
        return str(staged_binary)
    except OSError, subprocess.TimeoutExpired:
        return None
    finally:
        if not preserve_staging:
            shutil.rmtree(staging, ignore_errors=True)


def _known_good_version(
    configured: str | None,
    base_env: Mapping[str, str],
) -> str | None:
    version = (
        (configured or "").strip()
        or base_env.get(CLAUDE_KNOWN_GOOD_VERSION_ENV, "").strip()
        or DEFAULT_KNOWN_GOOD_CLAUDE_VERSION
    )
    return version if _VERSION_RE.fullmatch(version) is not None else None


def _offline_node_environment(base_env: Mapping[str, str]) -> dict[str, str]:
    """Build a minimal environment for a cache-only npm repair."""

    environment = {
        "HOME": str(Path.home()),
        "PATH": base_env.get("PATH", os.defpath),
        "NPM_CONFIG_AUDIT": "false",
        "NPM_CONFIG_FUND": "false",
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    }
    for key in ("TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL"):
        value = base_env.get(key)
        if value:
            environment[key] = value
    return environment


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
