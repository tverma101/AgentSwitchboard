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


def _atomic_write(path: Path, document: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(document)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)


def install_context_policy(config_dir: Path | None = None) -> bool:
    """Install or update the managed global context policy idempotently."""

    path = instructions_path(config_dir)
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

    recovery = backup_path(path)
    if path.exists() and not recovery.exists():
        recovery.write_bytes(path.read_bytes())
    _atomic_write(path, updated)
    return True


def uninstall_context_policy(config_dir: Path | None = None) -> bool:
    """Remove only the managed block, leaving user instructions untouched."""

    path = instructions_path(config_dir)
    if not path.exists():
        return False
    existing = _read(path)
    span = _managed_span(existing)
    if span is None:
        return False
    start, end = span
    _atomic_write(path, f"{existing[:start]}{existing[end:]}")
    return True


def context_policy_status(config_dir: Path | None = None) -> dict[str, object]:
    """Return a sanitized, machine-readable policy installation receipt."""

    path = instructions_path(config_dir)
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
        "path": str(path),
        "installed": installed,
        "policy_version": installed_version,
        "policy_digest": installed_digest,
        "expected_digest": policy_digest(),
        "backup_path": str(recovery),
        "backup_exists": recovery.is_file(),
    }
