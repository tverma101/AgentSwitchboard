"""Trusted, metadata-only promotion gates for learned skill replacements."""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal

PromotionDecision = Literal["pass", "fail", "error", "no_gate"]


@dataclass(frozen=True, slots=True)
class SkillPromotionCandidate:
    """Untrusted candidate data supplied to a trusted deterministic evaluator."""

    skill_key: str
    current_content: str
    candidate_content: str
    scope: str
    project_key: str


@dataclass(frozen=True, slots=True)
class TrustedSkillPromotionCheck:
    """Repo/user-authored evaluator selected independently of generated skill text."""

    check_id: str
    version: str
    evaluator: Callable[[SkillPromotionCandidate], bool]


_TRUSTED_CHECKS: dict[str, TrustedSkillPromotionCheck] = {}
_RECEIPT_NAME = "skill-promotion-receipts.jsonl"


def register_trusted_skill_promotion_check(
    skill_key: str,
    *,
    check_id: str,
    version: str,
    evaluator: Callable[[SkillPromotionCandidate], bool],
) -> None:
    """Register one trusted promotion evaluator for a generated skill key.

    Registration is code-driven on purpose. Generated ``SKILL.md`` content is
    untrusted and cannot select, replace, or provide an executable check.
    """

    normalized_key = skill_key.strip()
    normalized_id = check_id.strip()
    normalized_version = version.strip()
    if not normalized_key:
        raise ValueError("skill promotion check requires a skill key")
    if (
        not normalized_id
        or len(normalized_id) > 128
        or "\n" in normalized_id
        or "\r" in normalized_id
    ):
        raise ValueError("skill promotion check requires a bounded single-line check id")
    if (
        not normalized_version
        or len(normalized_version) > 64
        or "\n" in normalized_version
        or "\r" in normalized_version
    ):
        raise ValueError("skill promotion check requires a bounded single-line version")
    if not callable(evaluator):
        raise ValueError("skill promotion evaluator must be callable")
    if normalized_key in _TRUSTED_CHECKS:
        raise ValueError(f"skill promotion check already registered for {normalized_key!r}")
    _TRUSTED_CHECKS[normalized_key] = TrustedSkillPromotionCheck(
        check_id=normalized_id,
        version=normalized_version,
        evaluator=evaluator,
    )


def unregister_trusted_skill_promotion_check(skill_key: str) -> bool:
    """Remove a previously trusted registration, normally during local teardown."""

    return _TRUSTED_CHECKS.pop(skill_key.strip(), None) is not None


def evaluate_skill_promotion(
    *,
    skill_key: str,
    current_content: str,
    candidate_content: str,
    scope: str,
    project_key: str,
    receipt_root: Path,
) -> bool:
    """Evaluate a replacement and append a content-free audit receipt.

    A missing gate preserves the existing structural-validation policy. A
    registered gate must return the literal boolean ``True``; false results and
    ordinary evaluator errors fail closed for that replacement. If a trusted
    gate is configured, failure to persist its receipt also fails closed.
    """

    check = _TRUSTED_CHECKS.get(skill_key)
    decision: PromotionDecision = "no_gate"
    runtime_ms = 0
    check_id = ""
    check_version = ""

    if check is not None:
        check_id = check.check_id
        check_version = check.version
        candidate = SkillPromotionCandidate(
            skill_key=skill_key,
            current_content=current_content,
            candidate_content=candidate_content,
            scope=scope,
            project_key=project_key,
        )
        started = monotonic()
        try:
            decision = "pass" if check.evaluator(candidate) is True else "fail"
        except Exception:
            decision = "error"
        runtime_ms = max(0, round((monotonic() - started) * 1000))

    try:
        _append_receipt(
            receipt_root,
            {
                "skill_key": skill_key,
                "current_digest": _digest(current_content),
                "candidate_digest": _digest(candidate_content),
                "check_id": check_id,
                "check_version": check_version,
                "decision": decision,
                "runtime_ms": runtime_ms,
            },
        )
    except OSError:
        return check is None
    return decision in {"pass", "no_gate"}


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _append_receipt(root: Path, receipt: dict[str, str | int]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(
        root / _RECEIPT_NAME,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("skill promotion receipt write made no progress")
            remaining = remaining[written:]
    finally:
        os.close(descriptor)
