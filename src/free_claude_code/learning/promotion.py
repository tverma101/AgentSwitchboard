"""Trusted per-skill promotion checks for FCC Learning.

The promotion sidecar is user/profile-authored state, never generated from
``SKILL.md``. Checks run as bounded direct argv calls (never through a shell),
with secure temporary paths substituted for the current and candidate skill.
"""

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Literal

from free_claude_code.core.trace import trace_event

PromotionDecision = Literal["pass", "fail", "error"]
_SIDECAR_VERSION = 1
_MAX_SIDECAR_BYTES = 256 * 1024
_MAX_ARGV_ITEMS = 32
_MAX_ARG_LENGTH = 512
_MAX_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class SkillPromotionCheck:
    """One trusted, bounded promotion check loaded from the profile sidecar."""

    check_id: str
    version: str
    argv: tuple[str, ...]
    timeout_seconds: float


class PromotionCheckConfigError(ValueError):
    """Raised when an opted-in promotion sidecar cannot be trusted as written."""


def _nonempty_string(value: Any, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise PromotionCheckConfigError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise PromotionCheckConfigError(f"{field} must be 1..{limit} characters")
    return normalized


def _load_check(sidecar: Path, skill_key: str) -> SkillPromotionCheck | None:
    """Load one externally selected check without consulting candidate content."""

    try:
        size = sidecar.stat().st_size
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PromotionCheckConfigError("promotion sidecar is unreadable") from exc
    if size > _MAX_SIDECAR_BYTES:
        raise PromotionCheckConfigError("promotion sidecar exceeds size limit")
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionCheckConfigError("promotion sidecar is invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("version") != _SIDECAR_VERSION:
        raise PromotionCheckConfigError("promotion sidecar version is unsupported")
    skills = payload.get("skills")
    if not isinstance(skills, dict):
        raise PromotionCheckConfigError("promotion sidecar skills must be an object")
    raw = skills.get(skill_key)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PromotionCheckConfigError("promotion check entry must be an object")

    check_id = _nonempty_string(raw.get("check_id"), field="check_id", limit=100)
    version = _nonempty_string(
        raw.get("check_version"), field="check_version", limit=50
    )
    argv = raw.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or len(argv) > _MAX_ARGV_ITEMS
        or not all(isinstance(item, str) for item in argv)
    ):
        raise PromotionCheckConfigError("promotion check argv is invalid")
    normalized_argv = tuple(argv)
    if any(not item or len(item) > _MAX_ARG_LENGTH for item in normalized_argv):
        raise PromotionCheckConfigError("promotion check argv item is invalid")

    timeout = raw.get("timeout_seconds", 30.0)
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise PromotionCheckConfigError("promotion check timeout must be numeric")
    timeout_seconds = float(timeout)
    if not 0.1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS:
        raise PromotionCheckConfigError("promotion check timeout is out of bounds")
    return SkillPromotionCheck(
        check_id=check_id,
        version=version,
        argv=normalized_argv,
        timeout_seconds=timeout_seconds,
    )


def _check_environment() -> dict[str, str]:
    """Expose only ordinary process/tooling environment, never provider secrets."""

    allowed = (
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "TMPDIR",
        "UV_CACHE_DIR",
        "VIRTUAL_ENV",
    )
    return {key: os.environ[key] for key in allowed if key in os.environ}


def _receipt(
    *,
    skill_key: str,
    current_content: str,
    candidate_content: str,
    check_id: str,
    check_version: str,
    decision: PromotionDecision,
    runtime_ms: int,
    error_type: str | None,
) -> None:
    trace_event(
        stage="learning",
        event="learning.skill_promotion",
        source="learning",
        skill_key=skill_key,
        current_digest=hashlib.sha256(current_content.encode()).hexdigest(),
        candidate_digest=hashlib.sha256(candidate_content.encode()).hexdigest(),
        check_id=check_id,
        check_version=check_version,
        decision=decision,
        runtime_ms=runtime_ms,
        error_type=error_type,
    )


def evaluate_skill_promotion(
    *,
    sidecar: Path,
    skill_key: str,
    current_content: str,
    candidate_content: str,
    project_key: str,
) -> PromotionDecision | None:
    """Run the trusted replacement gate and emit a metadata-only receipt."""

    started = monotonic()
    try:
        check = _load_check(sidecar, skill_key)
    except PromotionCheckConfigError as exc:
        _receipt(
            skill_key=skill_key,
            current_content=current_content,
            candidate_content=candidate_content,
            check_id="sidecar-config",
            check_version=str(_SIDECAR_VERSION),
            decision="error",
            runtime_ms=max(0, round((monotonic() - started) * 1000)),
            error_type=type(exc).__name__,
        )
        return "error"
    if check is None:
        return None

    project = Path(project_key)
    if not project.is_dir():
        _receipt(
            skill_key=skill_key,
            current_content=current_content,
            candidate_content=candidate_content,
            check_id=check.check_id,
            check_version=check.version,
            decision="error",
            runtime_ms=max(0, round((monotonic() - started) * 1000)),
            error_type="PromotionProjectUnavailable",
        )
        return "error"

    decision: PromotionDecision
    error_type: str | None = None
    with tempfile.TemporaryDirectory(prefix="fcc-skill-promotion-") as temp_dir:
        temp_root = Path(temp_dir)
        current_path = temp_root / "current.md"
        candidate_path = temp_root / "candidate.md"
        current_path.write_text(current_content, encoding="utf-8")
        candidate_path.write_text(candidate_content, encoding="utf-8")
        substitutions = {
            "{current}": str(current_path),
            "{candidate}": str(candidate_path),
            "{project}": str(project),
        }
        argv = [substitutions.get(argument, argument) for argument in check.argv]
        try:
            completed = subprocess.run(
                argv,
                cwd=project,
                env=_check_environment(),
                capture_output=True,
                timeout=check.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            decision = "error"
            error_type = "PromotionCheckTimeout"
        except OSError:
            decision = "error"
            error_type = "PromotionCheckExecError"
        else:
            decision = "pass" if completed.returncode == 0 else "fail"

    _receipt(
        skill_key=skill_key,
        current_content=current_content,
        candidate_content=candidate_content,
        check_id=check.check_id,
        check_version=check.version,
        decision=decision,
        runtime_ms=max(0, round((monotonic() - started) * 1000)),
        error_type=error_type,
    )
    return decision
