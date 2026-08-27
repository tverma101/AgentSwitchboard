"""Automatic, bounded reviewer-scar learning around Claude Agent tool calls.

The Agent PreToolUse hook has the real delegated task, while PostToolUse has both
that task input and the subagent's final result. This module uses those supported
boundaries to inject task-matched scars and to persist only an explicitly
nominated, counterfactually useful A1 scar candidate. Background Agent calls keep
only a short-lived metadata-only task plan keyed by hashed session/agent ids.
"""

import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from free_claude_code.core.interprocess_lock import InterprocessFileLock

from .config import profile_home
from .reviewer_flow import (
    ExitTicketResult,
    ReviewerTaskPlan,
    admit_exit_candidate,
    build_reviewer_plan,
    parse_exit_ticket,
)
from .reviewer_scars import (
    ExitStatus,
    PreventionClass,
    ReviewerPack,
    ReviewerScarError,
    ScarCandidate,
    ScarKind,
    ScarRegistry,
    ScarSelection,
    ScarState,
    TaskFingerprint,
    VerificationLevel,
)

AUTO_SCAR_PREFIX: Final = "A1|"
AUTO_CONTEXT_START: Final = "<fcc-reviewer-auto-v1>"
AUTO_CONTEXT_END: Final = "</fcc-reviewer-auto-v1>"
MAX_AUTO_LINE_BYTES: Final = 1_024
MAX_AUTO_SCAN_BYTES: Final = 16_384
MAX_PENDING_TASKS: Final = 64
PENDING_TTL_SECONDS: Final = 24 * 60 * 60
PENDING_LOCK_TIMEOUT_SECONDS: Final = 5.0
_PENDING_SCHEMA: Final = 1
_SIGNAL_RE = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")


@dataclass(frozen=True, slots=True)
class AutoScarOutcome:
    """Content-free result of one automatic scar-learning attempt."""

    promoted: bool
    reason: str
    scar_id: str | None = None

    def parent_context(self) -> str:
        if self.promoted and self.scar_id:
            return f"FCC reviewer auto-learn: promoted scar={self.scar_id}."
        return f"FCC reviewer auto-learn: DROP reason={self.reason}."


@dataclass(frozen=True, slots=True)
class AutoReviewResult:
    """Validated X1 result plus its durable-learning outcome."""

    ticket: ExitTicketResult
    outcome: AutoScarOutcome

    def parent_context(self) -> str:
        return f"{self.ticket.parent_context()}\n{self.outcome.parent_context()}"


def augment_agent_input(
    tool_input: Mapping[str, object],
    *,
    profile: str | None = None,
) -> dict[str, object] | None:
    """Append bounded reviewer context to an Agent prompt without auto-approving it."""

    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    base_input = _base_agent_input(tool_input)
    plan = build_reviewer_plan(base_input, profile=profile)
    context = _agent_contract(plan)
    updated = dict(base_input)
    updated["prompt"] = (
        f"{str(base_input['prompt']).rstrip()}\n\n"
        f"{AUTO_CONTEXT_START}\n{context}\n{AUTO_CONTEXT_END}"
    )
    return updated


def process_agent_result(
    payload: Mapping[str, object],
    *,
    profile: str | None = None,
) -> AutoReviewResult | None:
    """Persist a completed Agent result or register a background task plan."""

    if payload.get("tool_name") != "Agent":
        return None
    raw_input = payload.get("tool_input")
    raw_response = payload.get("tool_response")
    if not isinstance(raw_input, Mapping) or not isinstance(raw_response, Mapping):
        return None

    base_input = _base_agent_input(raw_input)
    try:
        plan = build_reviewer_plan(base_input, profile=profile)
    except OSError, ReviewerScarError, ValueError:
        return None

    status = raw_response.get("status")
    if status == "async_launched":
        session_id = payload.get("session_id")
        agent_id = raw_response.get("agentId")
        if isinstance(session_id, str) and isinstance(agent_id, str):
            try:
                PendingReviewerTasks(profile).save(session_id, agent_id, plan)
            except OSError, ReviewerScarError:
                pass
        return None
    if status != "completed":
        return None

    message = _agent_response_text(raw_response)
    return persist_from_message(
        message,
        plan=plan,
        registry=ScarRegistry(profile),
    )


def process_background_subagent_stop(
    payload: Mapping[str, object],
    *,
    profile: str | None = None,
) -> AutoReviewResult | None:
    """Finish auto-learning for a background Agent using its metadata-only plan."""

    session_id = payload.get("session_id")
    agent_id = payload.get("agent_id")
    if not isinstance(session_id, str) or not isinstance(agent_id, str):
        return None
    try:
        plan = PendingReviewerTasks(profile).pop(session_id, agent_id)
    except OSError, ReviewerScarError:
        return None
    if plan is None:
        return None
    message = payload.get("last_assistant_message")
    return persist_from_message(
        message if isinstance(message, str) else None,
        plan=plan,
        registry=ScarRegistry(profile),
    )


def persist_from_message(
    message: str | None,
    *,
    plan: ReviewerTaskPlan,
    registry: ScarRegistry,
) -> AutoReviewResult:
    """Parse X1+A1, enforce task relevance, and persist only a passing candidate."""

    ticket_result = parse_exit_ticket(message)
    ticket = ticket_result.ticket
    if ticket is None:
        return AutoReviewResult(
            ticket_result,
            AutoScarOutcome(False, f"x1_{ticket_result.reason}"),
        )
    if not ticket.learn_candidate:
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, "x1_learn_false"))
    if ticket.status is ExitStatus.FAIL:
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, "x1_failed"))

    parsed = _parse_auto_candidate(message)
    if isinstance(parsed, str):
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, parsed))
    fields = parsed

    try:
        pack = ReviewerPack(fields["pack"])
        kind = ScarKind(fields["kind"])
        prevention = PreventionClass(fields["pain"])
    except ValueError:
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, "a1_invalid_enum"))

    if pack not in plan.packs:
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, "a1_pack_not_selected"))
    if kind is ScarKind.EFFICIENCY and pack is not ReviewerPack.EFFICIENCY:
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, "a1_kind_pack_mismatch"))
    if fields["when"] != ticket.cave or fields["rule"] != ticket.next_action:
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, "a1_x1_semantic_mismatch"))

    evidence = () if fields["ev"] == "-" else tuple(fields["ev"].split(","))
    if tuple(sorted(set(evidence))) != tuple(sorted(set(ticket.evidence))):
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, "a1_x1_evidence_mismatch"))
    if not _scope_matches_task(fields["scope"], plan.fingerprint):
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, "a1_scope_not_task_relevant"))

    candidate = ScarCandidate(
        pack=pack,
        kind=kind,
        scope=fields["scope"],
        condition=fields["when"],
        rule=fields["rule"],
        state=_state_from_ticket(ticket.status, ticket.verification),
        prevention=prevention,
        evidence=evidence,
    )
    try:
        decision = admit_exit_candidate(ticket_result, candidate)
        if not decision.promote or decision.record is None:
            return AutoReviewResult(
                ticket_result,
                AutoScarOutcome(False, decision.reason),
            )
        record = registry.upsert(decision)
    except OSError, ReviewerScarError, ValueError:
        return AutoReviewResult(ticket_result, AutoScarOutcome(False, "persistence_rejected"))
    return AutoReviewResult(
        ticket_result,
        AutoScarOutcome(True, "counterfactual_gate_passed", record.scar_id),
    )


def _agent_contract(plan: ReviewerTaskPlan) -> str:
    base = plan.context()
    allowed = ",".join(pack.value for pack in plan.packs)
    if not allowed:
        return (
            f"{base}\nFCC auto-scar: no task-matched pack is enabled; set learn=0 "
            "and do not emit A1."
        )
    return (
        f"{base}\n"
        "FCC auto-scar: only when X1 learn=1, also return exactly one line: "
        "A1|pack=<pack>|kind=<C1|N1|T1|E1>|scope=<compact-scope>|"
        "when=<same-as-X1-cave>|rule=<same-as-X1-next>|"
        "pain=<data_loss|false_completion|provider_spend|hours_debugging|"
        "dangerous_duplication>|ev=<same-as-X1-ev>. "
        f"pack must be one of [{allowed}]. Otherwise emit no A1."
    )


def _parse_auto_candidate(message: str | None) -> dict[str, str] | str:
    if not isinstance(message, str) or not message.strip():
        return "missing_a1"
    bounded = message.encode("utf-8")[-MAX_AUTO_SCAN_BYTES:].decode(
        "utf-8", errors="ignore"
    )
    lines = [
        line.strip()
        for line in bounded.splitlines()
        if line.strip().startswith(AUTO_SCAR_PREFIX)
    ]
    if not lines:
        return "missing_a1"
    if len(lines) != 1:
        return "multiple_a1_lines"
    line = lines[0]
    if len(line.encode("utf-8")) > MAX_AUTO_LINE_BYTES:
        return "a1_too_large"

    parts = line.split("|")
    if not parts or parts[0] != "A1":
        return "malformed_a1"
    fields: dict[str, str] = {}
    for part in parts[1:]:
        key, separator, value = part.partition("=")
        if not separator or not key or key in fields:
            return "malformed_a1"
        if not value or "\n" in value or "\r" in value or "|" in value:
            return "malformed_a1"
        fields[key] = value
    required = {"pack", "kind", "scope", "when", "rule", "pain", "ev"}
    if set(fields) != required:
        return "a1_fields_invalid"
    return fields


def _state_from_ticket(status: ExitStatus, verification: VerificationLevel) -> ScarState:
    if verification is VerificationLevel.NONE:
        return ScarState.OBSERVED
    if status is ExitStatus.DONE and verification in {
        VerificationLevel.TESTS,
        VerificationLevel.LIVE,
        VerificationLevel.CI,
        VerificationLevel.DEVICE,
    }:
        return ScarState.VERIFIED
    return ScarState.REPRODUCED


def _scope_matches_task(scope: str, fingerprint: TaskFingerprint) -> bool:
    if not fingerprint.scopes:
        return True
    signals = set(_SIGNAL_RE.findall(scope.casefold()))
    return bool(signals.intersection(fingerprint.scopes))


def _base_agent_input(tool_input: Mapping[str, object]) -> dict[str, object]:
    base = dict(tool_input)
    prompt = base.get("prompt")
    if not isinstance(prompt, str):
        return base
    start = prompt.rfind(AUTO_CONTEXT_START)
    end = prompt.rfind(AUTO_CONTEXT_END)
    if start >= 0 and end > start and not prompt[end + len(AUTO_CONTEXT_END) :].strip():
        base["prompt"] = prompt[:start].rstrip()
    return base


def _agent_response_text(response: Mapping[str, object]) -> str:
    content = response.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


class PendingReviewerTasks:
    """Short-lived metadata-only plan handoff for background Agent runs."""

    def __init__(self, profile: str | None = None) -> None:
        root = profile_home(profile)
        self._path = root / "reviewer-pending.json"
        self._lock_path = root / "reviewer-pending.lock"

    def save(
        self,
        session_id: str,
        agent_id: str,
        plan: ReviewerTaskPlan,
    ) -> None:
        key = _pending_key(session_id, agent_id)
        with self._locked():
            entries = self._read_entries()
            now = int(time.time())
            entries = _prune_entries(entries, now)
            entries[key] = {
                "created_at": now,
                "packs": [pack.value for pack in plan.packs],
                "scopes": list(plan.fingerprint.scopes),
                "operations": list(plan.fingerprint.operations),
                "risks": list(plan.fingerprint.risks),
            }
            if len(entries) > MAX_PENDING_TASKS:
                ordered = sorted(
                    entries,
                    key=lambda item: int(entries[item].get("created_at", 0)),
                )
                for stale in ordered[: len(entries) - MAX_PENDING_TASKS]:
                    entries.pop(stale, None)
            self._write_entries(entries)

    def pop(self, session_id: str, agent_id: str) -> ReviewerTaskPlan | None:
        key = _pending_key(session_id, agent_id)
        with self._locked():
            entries = _prune_entries(self._read_entries(), int(time.time()))
            value = entries.pop(key, None)
            self._write_entries(entries)
        if not isinstance(value, Mapping):
            return None
        try:
            fingerprint = TaskFingerprint(
                scopes=_string_tuple(value.get("scopes")),
                operations=_string_tuple(value.get("operations")),
                risks=_string_tuple(value.get("risks")),
            )
            packs = tuple(ReviewerPack(item) for item in _string_tuple(value.get("packs")))
        except ValueError:
            return None
        return ReviewerTaskPlan(
            fingerprint=fingerprint,
            packs=packs,
            selection=ScarSelection(lines=(), bytes_used=0, estimated_tokens=0),
        )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = InterprocessFileLock(self._lock_path)
        if not lock.acquire(wait=True, timeout=PENDING_LOCK_TIMEOUT_SECONDS):
            raise ReviewerScarError("timed out waiting for reviewer pending lock")
        try:
            yield
        finally:
            lock.release()

    def _read_entries(self) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except OSError, UnicodeDecodeError, json.JSONDecodeError:
            return {}
        if not isinstance(payload, Mapping) or payload.get("schema") != _PENDING_SCHEMA:
            return {}
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, Mapping):
            return {}
        entries: dict[str, dict[str, object]] = {}
        for key, value in raw_entries.items():
            if isinstance(key, str) and isinstance(value, Mapping):
                entries[key] = dict(value)
        return entries

    def _write_entries(self, entries: Mapping[str, Mapping[str, object]]) -> None:
        payload = {"schema": _PENDING_SCHEMA, "entries": dict(entries)}
        encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(encoded)
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            os.replace(temporary, self._path)
            if os.name != "nt":
                os.chmod(self._path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)


def _pending_key(session_id: str, agent_id: str) -> str:
    return hashlib.sha256(f"{session_id}\0{agent_id}".encode("utf-8")).hexdigest()[:24]


def _prune_entries(
    entries: Mapping[str, Mapping[str, object]],
    now: int,
) -> dict[str, dict[str, object]]:
    fresh: dict[str, dict[str, object]] = {}
    for key, value in entries.items():
        created = value.get("created_at")
        if not isinstance(created, int) or isinstance(created, bool):
            continue
        if now - created > PENDING_TTL_SECONDS:
            continue
        fresh[key] = dict(value)
    return fresh


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return ()
    return tuple(value)


__all__ = [
    "AUTO_CONTEXT_END",
    "AUTO_CONTEXT_START",
    "AUTO_SCAR_PREFIX",
    "AutoReviewResult",
    "AutoScarOutcome",
    "PendingReviewerTasks",
    "augment_agent_input",
    "persist_from_message",
    "process_agent_result",
    "process_background_subagent_stop",
]
