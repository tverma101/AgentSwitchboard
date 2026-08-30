"""Bounded reviewer context and exit-ticket seams for Claude Code hooks."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from .config import configured_profile, normalize_profile
from .reviewer_config import ReviewerPackSettings
from .reviewer_scars import (
    ExitStatus,
    ReviewerPack,
    ReviewerScarError,
    ScarCandidate,
    ScarDecision,
    ScarRegistry,
    ScarSelection,
    SubagentExitTicket,
    TaskFingerprint,
    admit_scar_candidate,
    resolve_enabled_packs,
    select_reviewer_packs,
    select_scars_for_context,
)

MAX_REVIEW_CONTEXT_BYTES: Final = 4_096
MAX_REVIEW_SCAR_BYTES: Final = 2_048
MAX_TASK_SIGNAL_BYTES: Final = 8_192
MAX_EXIT_SCAN_BYTES: Final = 16_384

_SIGNAL_RE = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_TASK_FIELDS = (
    "prompt",
    "description",
    "subagent_type",
    "type",
    "task",
    "scope",
    "operation",
    "risk",
)
_SIGNAL_ALIASES = {
    "accessibility": "macos",
    "api": "provider",
    "chrome": "browser",
    "claude": "provider",
    "codex": "native",
    "darwin": "macos",
    "mac": "macos",
    "playwright": "browser",
    "pr": "github",
    "pull-request": "github",
    "tcc": "macos",
    "terminal": "native",
    "web": "browser",
}
_RISK_ALIASES = {
    "duplicate": "duplicate-code",
    "duplicate-code": "duplicate-code",
    "duplicate-runtime": "duplicate-runtime",
    "false-complete": "false-completion",
    "false-completion": "false-completion",
    "large-context": "large-context",
    "staged-merged": "staged-vs-merged",
}


@dataclass(frozen=True, slots=True)
class ReviewerTaskPlan:
    """The only reviewer material a hook may inject into a task."""

    fingerprint: TaskFingerprint
    packs: tuple[ReviewerPack, ...]
    selection: ScarSelection

    def context(self) -> str:
        pack_text = ",".join(pack.value for pack in self.packs) or "-"
        lines = [
            (
                f"FCC reviewer packs={pack_text}; scars={len(self.selection.lines)}; "
                f"bytes={self.selection.bytes_used}; metadata-only"
            )
        ]
        if self.selection.lines:
            lines.append("FCC compact scars:")
            lines.extend(self.selection.lines)
        lines.append(
            "FCC worker exit: return exactly one bounded X1 ticket "
            "(st, impl, verify, blk, cave, learn, ev, next)."
        )
        value = "\n".join(lines)
        if len(value.encode("utf-8")) > MAX_REVIEW_CONTEXT_BYTES:
            raise ReviewerScarError("reviewer hook context exceeds its byte bound")
        return value


@dataclass(frozen=True, slots=True)
class ExitTicketResult:
    """A parsed private ticket plus its minimal Claude-visible projection."""

    ticket: SubagentExitTicket | None
    reason: str

    def model_projection(self) -> str:
        """Return actionable semantics without private receipt/protocol fields."""

        ticket = self.ticket
        if ticket is None:
            return (
                "FCC reviewer result unavailable; status=UNVERIFIED; "
                "parent should request a bounded reviewer result."
            )

        parts = [
            "FCC reviewer result:",
            f"status={ticket.status.value};",
            f"implemented={int(ticket.implemented)};",
            f"verification={ticket.verification.value};",
        ]
        if ticket.blocker != "-":
            parts.append(f"blocker={ticket.blocker};")
        if ticket.cave != "-":
            parts.append(f"cave={ticket.cave};")
        if ticket.next_action != "-":
            parts.append(f"next={ticket.next_action};")
        return " ".join(parts).rstrip(";")

    def parent_context(self) -> str:
        """Compatibility alias for the model-safe parent projection."""

        return self.model_projection()


def fingerprint_task(value: Mapping[str, object] | str) -> TaskFingerprint:
    """Extract cheap canonical signals without retaining task text."""

    texts = _task_texts(value)
    raw_signals: set[str] = set()
    remaining = MAX_TASK_SIGNAL_BYTES
    for text in texts:
        if remaining <= 0:
            break
        bounded = text.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
        remaining -= len(bounded.encode("utf-8"))
        raw_signals.update(_SIGNAL_RE.findall(bounded.casefold()))

    signals = {_SIGNAL_ALIASES.get(signal, signal) for signal in raw_signals}
    risks = {_RISK_ALIASES.get(signal, signal) for signal in signals}
    return TaskFingerprint(
        scopes=tuple(
            sorted(signals & {"browser", "ci", "github", "macos", "native", "provider"})
        ),
        operations=tuple(
            sorted(
                signals
                & {
                    "benchmark",
                    "cleanup",
                    "compatibility",
                    "fix",
                    "implement",
                    "integration",
                    "new-helper",
                    "new-router",
                    "new-runtime",
                    "optimize",
                    "performance",
                    "refactor",
                    "release",
                }
            )
        ),
        risks=tuple(
            sorted(
                risks
                & {
                    "cost",
                    "duplicate-code",
                    "duplicate-runtime",
                    "false-completion",
                    "large-context",
                    "repeated-work",
                    "staged-vs-merged",
                    "token-pressure",
                }
            )
        ),
    )


def build_reviewer_plan(
    value: Mapping[str, object] | str,
    *,
    profile: str | None = None,
    registry: ScarRegistry | None = None,
) -> ReviewerTaskPlan:
    """Build a bounded task plan from the profile-isolated scar registry."""

    fingerprint = fingerprint_task(value)
    packs = resolve_enabled_packs(
        set(select_reviewer_packs(fingerprint)),
        ReviewerPackSettings(profile).overrides(),
    )
    active_registry = registry or ScarRegistry(profile)
    selection = select_scars_for_context(
        active_registry.load(),
        packs,
        max_bytes=MAX_REVIEW_SCAR_BYTES,
        max_tokens=MAX_REVIEW_SCAR_BYTES // 4,
        max_records=8,
    )
    return ReviewerTaskPlan(
        fingerprint=fingerprint,
        packs=packs,
        selection=selection,
    )


def reviewer_context_for_task(
    value: Mapping[str, object] | str,
    *,
    profile: str | None = None,
    registry: ScarRegistry | None = None,
) -> str:
    """Return hook-safe context; a bad registry never breaks Claude Code."""

    try:
        return build_reviewer_plan(value, profile=profile, registry=registry).context()
    except OSError, ReviewerScarError, ValueError:
        return (
            "FCC reviewer context unavailable; no scar was injected. "
            "Return one bounded X1 ticket and treat reviewer state as unverified."
        )


def parse_exit_ticket(message: str | None) -> ExitTicketResult:
    """Parse exactly one X1 line and discard all other assistant text."""

    if not isinstance(message, str) or not message.strip():
        return ExitTicketResult(None, "missing_assistant_message")
    bounded = message.encode("utf-8")[-MAX_EXIT_SCAN_BYTES:].decode(
        "utf-8", errors="ignore"
    )
    candidates = [
        line.strip() for line in bounded.splitlines() if line.strip().startswith("X1|")
    ]
    if not candidates:
        return ExitTicketResult(None, "missing_x1")
    if len(candidates) != 1:
        return ExitTicketResult(None, "multiple_x1_lines")
    try:
        return ExitTicketResult(SubagentExitTicket.parse(candidates[0]), "accepted")
    except ReviewerScarError, ValueError:
        return ExitTicketResult(None, "malformed_x1")


def admit_exit_candidate(
    result: ExitTicketResult,
    candidate: ScarCandidate,
) -> ScarDecision:
    """Run a nominated candidate through the existing counterfactual gate."""

    ticket = result.ticket
    if ticket is None:
        return ScarDecision(False, "exit_ticket_invalid")
    if ticket.status is ExitStatus.FAIL:
        return ScarDecision(False, "exit_ticket_failed")
    if not ticket.learn_candidate:
        return ScarDecision(False, "exit_ticket_did_not_nominate")
    if ticket.cave == "-":
        return ScarDecision(False, "exit_ticket_missing_cave")
    if not set(ticket.evidence).intersection(candidate.evidence):
        return ScarDecision(False, "exit_ticket_evidence_not_referenced")
    return admit_scar_candidate(candidate)


def persist_exit_candidate(
    result: ExitTicketResult,
    candidate: ScarCandidate,
    *,
    registry: ScarRegistry,
) -> ScarDecision:
    """Persist only an explicitly supplied candidate that passes the gate."""

    decision = admit_exit_candidate(result, candidate)
    if decision.promote:
        registry.upsert(decision)
    return decision


def reviewer_status(
    *,
    profile: str | None = None,
    registry: ScarRegistry | None = None,
    settings: ReviewerPackSettings | None = None,
) -> dict[str, Any]:
    """Return the local reviewer control state without transcript material."""

    selected_profile = (
        configured_profile() if profile is None else normalize_profile(profile)
    )
    active_settings = settings or ReviewerPackSettings(selected_profile)
    overrides = active_settings.overrides()
    active_registry = registry or ScarRegistry(selected_profile)
    packs = [
        {
            "pack": pack.value,
            "override": overrides.get(pack),
            "mode": (
                "enabled"
                if overrides.get(pack) is True
                else "disabled"
                if overrides.get(pack) is False
                else "automatic"
            ),
        }
        for pack in ReviewerPack
    ]
    return {
        "profile": selected_profile,
        "packs": packs,
        "scars": [record.as_dict() for record in active_registry.load()],
    }


def _task_texts(value: Mapping[str, object] | str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    texts: list[str] = []
    for key in _TASK_FIELDS:
        item = value.get(key)
        if isinstance(item, str):
            texts.append(item)
    return tuple(texts)


__all__ = [
    "MAX_REVIEW_CONTEXT_BYTES",
    "MAX_REVIEW_SCAR_BYTES",
    "ExitTicketResult",
    "ReviewerTaskPlan",
    "admit_exit_candidate",
    "build_reviewer_plan",
    "fingerprint_task",
    "parse_exit_ticket",
    "persist_exit_candidate",
    "reviewer_context_for_task",
    "reviewer_status",
]
