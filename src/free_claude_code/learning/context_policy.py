"""Managed global Claude instructions for bounded tool-output behavior."""

import hashlib
import os
import tempfile
from contextlib import suppress
from pathlib import Path

POLICY_VERSION = "1"
POLICY_BEGIN = "<!-- FCC_CONTEXT_POLICY:BEGIN -->"
POLICY_END = "<!-- FCC_CONTEXT_POLICY:END -->"
POLICY_ENV = "FCC_CLAUDE_GLOBAL_INSTRUCTIONS"
CONTEXT_INTERVENTION_ENV = "FCC_CONTEXT_GOVERNOR_ENABLED"
_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
_DISABLED_REASON = (
    "FCC-managed Claude context instructions are disabled until Claude Code "
    "compatibility is certified"
)

_POLICY_BODY = """## FCC context discipline

Treat context as a bounded budget. Keep ordinary exploration small and preserve
the full result outside the conversation when a command or file is large.

- Check file size and line count before reading an unknown or generated file.
- Prefer targeted `rg`, `grep`, `head`, `tail`, `sed`, `git diff --stat`, and
  bounded Read slices over `cat`, whole-file dumps, or unfiltered recursive
  output.
- Return the smallest useful contiguous slice and expand only when evidence
  requires it.
- Reuse unchanged observations; do not reread the same file or result without
  a reason.
- Write verbose test, build, and shell output to a local log, then return a
  bounded summary plus its path instead of injecting the full stream.
- On a failure, show the assertion or traceback neighborhood first and keep the
  complete log available for a targeted follow-up.
- Query selected keys or records from JSON/JSONL/data files instead of dumping
  the entire document.
- Do not print secrets, environment files, credentials, or authentication
  material into the conversation.
- Do not recursively dump directory trees; use bounded depth and filters.

When context pressure rises, enter CONSERVE mode: narrow reads, reuse prior
observations, and summarize before starting unrelated exploration. At CRITICAL
pressure, stop broad exploration and checkpoint or compact before continuing.
Do not deliberately create repeated compactions by allowing avoidable output
to balloon.
"""


def policy_block() -> str:
    """Return the exact managed Markdown block installed into Claude."""

    return "\n".join(
        (
            POLICY_BEGIN,
            f"<!-- FCC_CONTEXT_POLICY_VERSION: {POLICY_VERSION} -->",
            _POLICY_BODY.rstrip(),
            POLICY_END,
        )
    )


def policy_digest(block: str | None = None) -> str:
    """Return the stable SHA-256 digest of a managed policy block."""

    value = policy_block() if block is None else block
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _block_version(block: str) -> str | None:
    prefix = "<!-- FCC_CONTEXT_POLICY_VERSION:"
    for line in block.splitlines():
        if line.startswith(prefix) and line.endswith(" -->"):
            return line[len(prefix) : -len(" -->")].strip()
    return None


def instructions_path(config_dir: Path | None = None) -> Path:
    """Return the global Claude instructions path for this installation."""

    override = os.environ.get(POLICY_ENV)
    if override and override.strip():
        return Path(override).expanduser()
    if config_dir is not None:
        return config_dir.expanduser() / "CLAUDE.md"
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(configured).expanduser() if configured else Path.home() / ".claude"
    return root / "CLAUDE.md"


def backup_path(path: Path) -> Path:
    """Return the one-time recovery copy path for ``path``."""

    return path.with_name(f"{path.name}.fcc-context-policy.bak")


def _context_intervention_enabled() -> bool:
    """Return whether an explicit isolated context experiment is enabled."""

    return (
        os.environ.get(CONTEXT_INTERVENTION_ENV, "").strip().lower() in _TRUTHY_VALUES
    )


def _managed_span(document: str) -> tuple[int, int] | None:
    begin_count = document.count(POLICY_BEGIN)
    end_count = document.count(POLICY_END)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise ValueError(
            "cannot safely update Claude instructions: FCC context policy "
            "markers are missing or duplicated"
        )
    begin = document.index(POLICY_BEGIN)
    end_marker = document.index(POLICY_END)
    if end_marker < begin:
        raise ValueError(
            "cannot safely update Claude instructions: FCC context policy "
            "end marker precedes begin marker"
        )
    begin_end = begin + len(POLICY_BEGIN)
    end_end = end_marker + len(POLICY_END)
    if (
        (begin and document[begin - 1] != "\n")
        or (begin_end < len(document) and document[begin_end] != "\n")
        or (end_marker and document[end_marker - 1] != "\n")
        or (end_end < len(document) and document[end_end] != "\n")
    ):
        raise ValueError(
            "cannot safely update Claude instructions: FCC context policy "
            "markers must occupy complete lines"
        )
    line_start = document.rfind("\n", 0, begin) + 1
    line_end = document.find("\n", end_marker + len(POLICY_END))
    if line_end == -1:
        line_end = len(document)
    return line_start, line_end


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _ensure_safe_target(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(
            "cannot safely update Claude instructions: target is a symbolic link"
        )
    if path.exists() and not path.is_file():
        raise ValueError(
            "cannot safely update Claude instructions: target is not a regular file"
        )


def _ensure_safe_backup(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(
            "cannot safely update Claude instructions: recovery copy is a symbolic link"
        )
    if path.exists() and not path.is_file():
        raise ValueError(
            "cannot safely update Claude instructions: recovery copy is not a regular file"
        )


def _atomic_write_bytes(path: Path, content: bytes, *, mode: int | None = None) -> None:
    _ensure_safe_target(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is not None:
        file_mode = mode
    elif path.exists():
        file_mode = path.stat().st_mode & 0o777
    else:
        file_mode = 0o600
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        os.fchmod(descriptor, file_mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)


def _atomic_write(path: Path, document: str) -> None:
    _atomic_write_bytes(path, document.encode("utf-8"))


def _backup_once(path: Path) -> None:
    if not path.exists():
        return
    _ensure_safe_target(path)
    recovery = backup_path(path)
    _ensure_safe_backup(recovery)
    if recovery.exists():
        return
    _atomic_write_bytes(
        recovery,
        path.read_bytes(),
        mode=0o600,
    )


def install_context_policy(config_dir: Path | None = None) -> bool:
    """Install the policy only inside an explicit future experiment.

    FCC must not write model-facing Claude instructions in its normal runtime.
    Keep the old reversible writer available for a separately isolated,
    explicitly enabled compatibility experiment, but make the safe default a
    no-op.
    """

    if not _context_intervention_enabled():
        return False

    path = instructions_path(config_dir)
    _ensure_safe_target(path)
    existing = _read(path)
    block = policy_block()
    span = _managed_span(existing)
    if span is None:
        if not existing:
            updated = f"{block}\n"
        elif existing.endswith("\n\n"):
            updated = f"{existing}{block}"
        elif existing.endswith("\n"):
            updated = f"{existing}\n{block}"
        else:
            updated = f"{existing}\n\n{block}"
    else:
        start, end = span
        if existing[start:end] == block:
            return False
        updated = f"{existing[:start]}{block}{existing[end:]}"

    _backup_once(path)
    _atomic_write(path, updated)
    return True


def uninstall_context_policy(config_dir: Path | None = None) -> bool:
    """Remove only the managed block, leaving user instructions untouched."""

    path = instructions_path(config_dir)
    _ensure_safe_target(path)
    if not path.exists():
        return False
    existing = _read(path)
    span = _managed_span(existing)
    if span is None:
        return False
    start, end = span
    _backup_once(path)
    _atomic_write(path, f"{existing[:start]}{existing[end:]}")
    return True


def context_policy_status(config_dir: Path | None = None) -> dict[str, object]:
    """Return a sanitized, machine-readable policy installation receipt."""

    path = instructions_path(config_dir)
    _ensure_safe_target(path)
    installed = False
    installed_version: str | None = None
    installed_digest: str | None = None
    if path.is_file():
        document = _read(path)
        span = _managed_span(document)
        if span is not None:
            installed = True
            start, end = span
            installed_block = document[start:end]
            installed_version = _block_version(installed_block)
            installed_digest = policy_digest(installed_block)
    recovery = backup_path(path)
    return {
        "enabled": _context_intervention_enabled(),
        "disabled_reason": None
        if _context_intervention_enabled()
        else _DISABLED_REASON,
        "path": str(path),
        "installed": installed,
        "policy_version": installed_version,
        "policy_digest": installed_digest,
        "expected_digest": policy_digest(),
        "backup_path": str(recovery),
        "backup_exists": recovery.is_file() and not recovery.is_symlink(),
    }
