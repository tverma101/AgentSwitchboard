"""Trusted per-skill promotion checks for FCC Learning.

Promotion checks are registered by trusted local code, never read from generated
``SKILL.md`` content.  Evaluators are intentionally in-process callables rather
than shell commands so candidate prose cannot become executable instructions.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Literal

from free_claude_code.core.trace import trace_event

PromotionDecision = Literal["pass", "fail", "error"]


@dataclass(frozen=True, slots=True)
class SkillPromotionContext:
    """Owned inputs supplied to one trusted candidate evaluator."""

    skill_key: str
    current_content: str
    candidate_content: str
    project_key: str


@dataclass(frozen=True, slots=True)
class SkillPromotionCheck:
    """One trusted, versioned promotion evaluator."""

    check_id: str
    version: str
    evaluator: Callable[[SkillPromotionContext], bool]


_CHECKS: dict[str, SkillPromotionCheck] = {}


def register_skill_promotion_check(
    skill_key: str,
    *,
    check_id: str,
    version: str,
    evaluator: Callable[[SkillPromotionContext], bool],
) -> None:
    """Register a trusted gate for one generated skill key.

    Registration is an explicit local-code action.  Generated candidate text is
    never consulted when selecting the evaluator.
    """

    normalized_key = skill_key.strip()
    normalized_id = check_id.strip()
    normalized_version = version.strip()
    if not normalized_key or len(normalized_key) > 200:
        raise ValueError("skill promotion key must be 1..200 characters")
    if not normalized_id or len(normalized_id) > 100:
        raise ValueError("skill promotion check id must be 1..100 characters")
    if not normalized_version or len(normalized_version) > 50:
        raise ValueError("skill promotion check version must be 1..50 characters")
    if not callable(evaluator):
        raise TypeError("skill promotion evaluator must be callable")

    candidate = SkillPromotionCheck(
        check_id=normalized_id,
        version=normalized_version,
        evaluator=evaluator,
    )
    existing = _CHECKS.get(normalized_key)
    if existing is not None and existing != candidate:
        raise ValueError(f"skill promotion check already registered for {normalized_key!r}")
    _CHECKS[normalized_key] = candidate


def unregister_skill_promotion_check(skill_key: str) -> None:
    """Remove one trusted registration, primarily for lifecycle/test cleanup."""

    _CHECKS.pop(skill_key.strip(), None)


def evaluate_skill_promotion(
    *,
    skill_key: str,
    current_content: str,
    candidate_content: str,
    project_key: str,
) -> PromotionDecision | None:
    """Evaluate a registered replacement gate and emit a metadata-only receipt."""

    check = _CHECKS.get(skill_key)
    if check is None:
        return None

    context = SkillPromotionContext(
        skill_key=skill_key,
        current_content=current_content,
        candidate_content=candidate_content,
        project_key=project_key,
    )
    started = monotonic()
    error_type: str | None = None
    try:
        result = check.evaluator(context)
    except Exception as exc:
        decision: PromotionDecision = "error"
        error_type = type(exc).__name__
    else:
        if result is True:
            decision = "pass"
        elif result is False:
            decision = "fail"
        else:
            decision = "error"
            error_type = "InvalidPromotionCheckResult"

    runtime_ms = max(0, round((monotonic() - started) * 1000))
    trace_event(
        stage="learning",
        event="learning.skill_promotion",
        source="learning",
        skill_key=skill_key,
        current_digest=hashlib.sha256(current_content.encode()).hexdigest(),
        candidate_digest=hashlib.sha256(candidate_content.encode()).hexdigest(),
        check_id=check.check_id,
        check_version=check.version,
        decision=decision,
        runtime_ms=runtime_ms,
        error_type=error_type,
    )
    return decision
