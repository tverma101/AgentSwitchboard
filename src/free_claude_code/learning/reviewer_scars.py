"""Bounded reviewer packs, compact scar memory, and subagent exit tickets.

The design reuses FCC Learning profiles and promotion boundaries. It intentionally
stores only compact typed metadata: no transcripts, prompts, hidden reasoning, or
credentials. Conservative reflection/deduplication concepts are adapted from
Letta Code's Apache-2.0 reflection agent; see docs/REVIEWER_SCARS_UPSTREAMS.md.
"""

import hashlib
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from free_claude_code.learning.config import profile_home

SCAR_SCHEMA = "fcc.reviewer-scars.v1"
MAX_SCAR_RECORDS = 512
MAX_STORE_BYTES = 256 * 1024
MAX_FIELD_BYTES = 512
MAX_EVIDENCE_REFS = 16
MAX_EXIT_TICKET_BYTES = 1_024

_SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key\s*[:=]|password\s*[:=]|authorization\s*[:=]|"
    r"bearer\s+[a-z0-9._-]{8,}|(?:access|refresh|auth)[_-]?token\s*[:=])"
)


class ReviewerScarError(ValueError):
    """Raised when reviewer/scar state violates the compact safety contract."""


class ReviewerPack(StrEnum):
    EFFICIENCY = "efficiency"
    EDGE_CASES = "edge-cases"
    IMPLEMENTATION_TRUTH = "implementation-truth"
    REDUNDANCY = "redundancy"


class ScarKind(StrEnum):
    CAVE = "C1"
    NEGATIVE = "N1"
    TRUTH = "T1"
    EFFICIENCY = "E1"


class ScarState(StrEnum):
    OBSERVED = "OBSERVED"
    REPRODUCED = "REPRODUCED"
    VERIFIED = "VERIFIED"
    UPSTREAM_BUG = "UPSTREAM_BUG"
    MITIGATED = "MITIGATED"
    STALE = "STALE"
    DISPROVEN = "DISPROVEN"
    SUPERSEDED = "SUPERSEDED"


class PreventionClass(StrEnum):
    NONE = "none"
    DATA_LOSS = "data_loss"
    FALSE_COMPLETION = "false_completion"
    PROVIDER_SPEND = "provider_spend"
    HOURS_DEBUGGING = "hours_debugging"
    DANGEROUS_DUPLICATION = "dangerous_duplication"


class ExitStatus(StrEnum):
    DONE = "DONE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"


class VerificationLevel(StrEnum):
    NONE = "none"
    LOCAL = "local"
    TESTS = "tests"
    LIVE = "live"
    CI = "ci"
    DEVICE = "device"


_PACK_ORDER = (
    ReviewerPack.EFFICIENCY,
    ReviewerPack.EDGE_CASES,
    ReviewerPack.IMPLEMENTATION_TRUTH,
    ReviewerPack.REDUNDANCY,
)
_STATE_RANK = {
    ScarState.OBSERVED: 0,
    ScarState.REPRODUCED: 1,
    ScarState.UPSTREAM_BUG: 2,
    ScarState.VERIFIED: 3,
    ScarState.MITIGATED: 4,
    ScarState.STALE: -1,
    ScarState.DISPROVEN: -2,
    ScarState.SUPERSEDED: -2,
}
_PROMOTABLE_STATES = frozenset(
    {
        ScarState.REPRODUCED,
        ScarState.VERIFIED,
        ScarState.UPSTREAM_BUG,
        ScarState.MITIGATED,
    }
)


@dataclass(frozen=True, slots=True)
class TaskFingerprint:
    """Cheap deterministic task signals used to choose the smallest review set."""

    scopes: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScarCandidate:
    pack: ReviewerPack
    kind: ScarKind
    scope: str
    condition: str
    rule: str
    state: ScarState
    prevention: PreventionClass = PreventionClass.NONE
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScarRecord:
    scar_id: str
    pack: ReviewerPack
    kind: ScarKind
    scope: str
    condition: str
    rule: str
    state: ScarState
    prevention: PreventionClass
    evidence: tuple[str, ...]
    history: tuple[ScarState, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Return safe metadata for local CLI/Admin presentation."""

        return {
            "scar_id": self.scar_id,
            "pack": self.pack.value,
            "kind": self.kind.value,
            "scope": self.scope,
            "condition": self.condition,
            "rule": self.rule,
            "state": self.state.value,
            "prevention": self.prevention.value,
            "evidence": list(self.evidence),
            "history": [state.value for state in self.history],
        }

    def compact(self) -> str:
        """Return stable machine-oriented shorthand without opaque private syntax."""

        evidence = ",".join(self.evidence) if self.evidence else "-"
        return (
            f"{self.kind.value}|pack={self.pack.value}|scope={self.scope}|"
            f"when={self.condition}|rule={self.rule}|state={self.state.value}|"
            f"pain={self.prevention.value}|ev={evidence}"
        )


@dataclass(frozen=True, slots=True)
class ScarDecision:
    promote: bool
    reason: str
    record: ScarRecord | None = None


@dataclass(frozen=True, slots=True)
class ScarSelection:
    lines: tuple[str, ...]
    bytes_used: int
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class SubagentExitTicket:
    status: ExitStatus
    implemented: bool
    verification: VerificationLevel
    blocker: str = "-"
    cave: str = "-"
    learn_candidate: bool = False
    evidence: tuple[str, ...] = ()
    next_action: str = "-"

    def compact(self) -> str:
        blocker = _safe_field(self.blocker, "blocker")
        cave = _safe_field(self.cave, "cave")
        next_action = _safe_field(self.next_action, "next_action")
        _validate_evidence(self.evidence)
        evidence = ",".join(self.evidence) if self.evidence else "-"
        value = (
            f"X1|st={self.status.value}|impl={int(self.implemented)}|"
            f"verify={self.verification.value}|blk={blocker}|cave={cave}|"
            f"learn={int(self.learn_candidate)}|ev={evidence}|next={next_action}"
        )
        _validate_compact_text(
            value, "exit ticket", MAX_EXIT_TICKET_BYTES, allow_pipe=True
        )
        return value

    @classmethod
    def parse(cls, value: str) -> SubagentExitTicket:
        _validate_compact_text(
            value, "exit ticket", MAX_EXIT_TICKET_BYTES, allow_pipe=True
        )
        parts = value.split("|")
        if not parts or parts[0] != "X1":
            raise ReviewerScarError("exit ticket must start with X1")
        fields: dict[str, str] = {}
        for part in parts[1:]:
            key, separator, raw = part.partition("=")
            if not separator or not key or key in fields:
                raise ReviewerScarError("exit ticket contains malformed fields")
            fields[key] = raw
        required = {"st", "impl", "verify", "blk", "cave", "learn", "ev", "next"}
        if set(fields) != required:
            raise ReviewerScarError("exit ticket fields do not match the X1 contract")
        if fields["impl"] not in {"0", "1"} or fields["learn"] not in {"0", "1"}:
            raise ReviewerScarError("exit ticket impl/learn fields must be 0 or 1")
        evidence = () if fields["ev"] == "-" else tuple(fields["ev"].split(","))
        _validate_evidence(evidence)
        return cls(
            status=ExitStatus(fields["st"]),
            implemented=fields["impl"] == "1",
            verification=VerificationLevel(fields["verify"]),
            blocker=_safe_field(fields["blk"], "blocker"),
            cave=_safe_field(fields["cave"], "cave"),
            learn_candidate=fields["learn"] == "1",
            evidence=evidence,
            next_action=_safe_field(fields["next"], "next_action"),
        )


def select_reviewer_packs(fingerprint: TaskFingerprint) -> tuple[ReviewerPack, ...]:
    """Choose only review lenses justified by cheap task signals."""

    scopes = {_normalized_signal(value) for value in fingerprint.scopes}
    operations = {_normalized_signal(value) for value in fingerprint.operations}
    risks = {_normalized_signal(value) for value in fingerprint.risks}
    selected: set[ReviewerPack] = set()

    if operations.intersection(
        {"benchmark", "performance", "optimize"}
    ) or risks.intersection(
        {"cost", "large-context", "repeated-work", "token-pressure"}
    ):
        selected.add(ReviewerPack.EFFICIENCY)

    if scopes.intersection(
        {"macos", "browser", "provider", "github", "ci", "native"}
    ) or operations.intersection({"performance", "compatibility", "integration"}):
        selected.add(ReviewerPack.EDGE_CASES)

    if operations.intersection(
        {"implement", "refactor", "integration", "release", "cleanup", "fix"}
    ) or risks.intersection({"false-completion", "staged-vs-merged"}):
        selected.add(ReviewerPack.IMPLEMENTATION_TRUTH)

    if operations.intersection(
        {"new-helper", "new-runtime", "cleanup", "new-router"}
    ) or risks.intersection({"duplicate-code", "duplicate-runtime"}):
        selected.add(ReviewerPack.REDUNDANCY)

    return tuple(pack for pack in _PACK_ORDER if pack in selected)


def resolve_enabled_packs(
    shared_enabled: set[ReviewerPack] | frozenset[ReviewerPack],
    profile_overrides: dict[ReviewerPack, bool] | None = None,
) -> tuple[ReviewerPack, ...]:
    """Resolve reusable shared packs with explicit per-profile overrides."""

    enabled = set(shared_enabled)
    for pack, value in (profile_overrides or {}).items():
        if value:
            enabled.add(pack)
        else:
            enabled.discard(pack)
    return tuple(pack for pack in _PACK_ORDER if pack in enabled)


def admit_scar_candidate(candidate: ScarCandidate) -> ScarDecision:
    """Apply the counterfactual prevention gate; default is DROP."""

    scope = _safe_field(candidate.scope, "scope")
    condition = _safe_field(candidate.condition, "condition")
    rule = _safe_field(candidate.rule, "rule")
    _validate_evidence(candidate.evidence)

    if candidate.prevention is PreventionClass.NONE:
        return ScarDecision(False, "no_concrete_prevented_pain")
    if candidate.state not in _PROMOTABLE_STATES:
        return ScarDecision(False, "evidence_state_not_promotable")
    if not candidate.evidence:
        return ScarDecision(False, "missing_evidence")

    scar_id = _scar_id(
        pack=candidate.pack,
        kind=candidate.kind,
        scope=scope,
        condition=condition,
        rule=rule,
    )
    record = ScarRecord(
        scar_id=scar_id,
        pack=candidate.pack,
        kind=candidate.kind,
        scope=scope,
        condition=condition,
        rule=rule,
        state=candidate.state,
        prevention=candidate.prevention,
        evidence=tuple(sorted(set(candidate.evidence))),
    )
    return ScarDecision(True, "counterfactual_prevention_supported", record)


def select_scars_for_context(
    records: tuple[ScarRecord, ...] | list[ScarRecord],
    enabled_packs: tuple[ReviewerPack, ...] | list[ReviewerPack],
    *,
    max_bytes: int = 4_096,
    max_tokens: int = 1_024,
    max_records: int = 12,
) -> ScarSelection:
    """Select a deterministic high-value slice under strict context budgets."""

    if max_bytes <= 0 or max_tokens <= 0 or max_records <= 0:
        raise ReviewerScarError("scar context budgets must be positive")
    byte_budget = min(max_bytes, max_tokens * 4)
    enabled = set(enabled_packs)
    active_states = _PROMOTABLE_STATES
    candidates = [
        record
        for record in records
        if record.pack in enabled and record.state in active_states
    ]
    candidates.sort(
        key=lambda record: (
            _PACK_ORDER.index(record.pack),
            -_STATE_RANK[record.state],
            record.scar_id,
        )
    )

    lines: list[str] = []
    bytes_used = 0
    for record in candidates:
        if len(lines) >= max_records:
            break
        line = record.compact()
        encoded = len((line + "\n").encode("utf-8"))
        if encoded > byte_budget - bytes_used:
            continue
        lines.append(line)
        bytes_used += encoded
    return ScarSelection(
        lines=tuple(lines),
        bytes_used=bytes_used,
        estimated_tokens=(bytes_used + 3) // 4,
    )


class ScarRegistry:
    """Profile-isolated compact scar registry with deterministic deduplication."""

    def __init__(self, profile: str | None = None) -> None:
        self._root = profile_home(profile)
        self._path = self._root / "reviewer-scars.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> tuple[ScarRecord, ...]:
        if self._path.is_symlink():
            raise ReviewerScarError("reviewer scar registry must not be a symlink")
        try:
            raw = self._path.read_text("utf-8")
        except FileNotFoundError:
            return ()
        except OSError as exc:
            raise ReviewerScarError("cannot read reviewer scar registry") from exc
        if len(raw.encode("utf-8")) > MAX_STORE_BYTES:
            raise ReviewerScarError("reviewer scar registry exceeds its size bound")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReviewerScarError("reviewer scar registry is invalid JSON") from exc
        if not isinstance(value, dict) or value.get("schema") != SCAR_SCHEMA:
            raise ReviewerScarError("reviewer scar registry schema is invalid")
        rows = value.get("records")
        if not isinstance(rows, list) or len(rows) > MAX_SCAR_RECORDS:
            raise ReviewerScarError("reviewer scar registry record set is invalid")
        records = tuple(_record_from_mapping(row) for row in rows)
        if len({record.scar_id for record in records}) != len(records):
            raise ReviewerScarError("reviewer scar registry contains duplicate ids")
        return records

    def upsert(self, decision: ScarDecision) -> ScarRecord:
        if not decision.promote or decision.record is None:
            raise ReviewerScarError("only promoted scar decisions may be persisted")
        incoming = decision.record
        records = list(self.load())
        for index, existing in enumerate(records):
            if existing.scar_id != incoming.scar_id:
                continue
            merged_state = max(
                (existing.state, incoming.state), key=_STATE_RANK.__getitem__
            )
            history = existing.history
            if merged_state != existing.state:
                history = (*history, existing.state)
            merged = replace(
                existing,
                state=merged_state,
                prevention=(
                    incoming.prevention
                    if incoming.prevention is not PreventionClass.NONE
                    else existing.prevention
                ),
                evidence=tuple(sorted(set(existing.evidence + incoming.evidence))),
                history=history,
            )
            records[index] = merged
            self._write(tuple(records))
            return merged
        if len(records) >= MAX_SCAR_RECORDS:
            raise ReviewerScarError("reviewer scar registry reached its record bound")
        records.append(incoming)
        records.sort(key=lambda record: record.scar_id)
        self._write(tuple(records))
        return incoming

    def update_state(self, scar_id: str, state: ScarState) -> ScarRecord:
        records = list(self.load())
        for index, existing in enumerate(records):
            if existing.scar_id != scar_id:
                continue
            if existing.state == state:
                return existing
            updated = replace(
                existing,
                state=state,
                history=(*existing.history, existing.state),
            )
            records[index] = updated
            self._write(tuple(records))
            return updated
        raise ReviewerScarError(f"unknown reviewer scar id: {scar_id}")

    def _write(self, records: tuple[ScarRecord, ...]) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._path.is_symlink():
            raise ReviewerScarError("reviewer scar registry must not be a symlink")
        payload = {
            "schema": SCAR_SCHEMA,
            "records": [_record_mapping(record) for record in records],
        }
        encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(encoded) > MAX_STORE_BYTES:
            raise ReviewerScarError("reviewer scar registry exceeds its size bound")
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            os.chmod(self._path, 0o600)
        except OSError as exc:
            raise ReviewerScarError("cannot write reviewer scar registry") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                temporary.unlink()


def _scar_id(
    *,
    pack: ReviewerPack,
    kind: ScarKind,
    scope: str,
    condition: str,
    rule: str,
) -> str:
    value = json.dumps(
        {
            "pack": pack.value,
            "kind": kind.value,
            "scope": scope,
            "condition": condition,
            "rule": rule,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _safe_field(value: str, name: str) -> str:
    _validate_compact_text(value, name, MAX_FIELD_BYTES)
    return value


def _validate_compact_text(
    value: str,
    name: str,
    max_bytes: int,
    *,
    allow_pipe: bool = False,
) -> None:
    if not isinstance(value, str) or not value:
        raise ReviewerScarError(f"{name} must be a non-empty string")
    if len(value.encode("utf-8")) > max_bytes:
        raise ReviewerScarError(f"{name} exceeds its byte bound")
    if "\n" in value or "\r" in value or ("|" in value and not allow_pipe):
        raise ReviewerScarError(f"{name} must remain one compact unambiguous field")
    if _SECRET_PATTERN.search(value):
        raise ReviewerScarError(f"{name} appears to contain secret material")


def _validate_evidence(evidence: tuple[str, ...] | list[str]) -> None:
    if not isinstance(evidence, tuple | list):
        raise ReviewerScarError("reviewer scar evidence must be an array")
    if len(evidence) > MAX_EVIDENCE_REFS:
        raise ReviewerScarError("too many reviewer scar evidence references")
    for item in evidence:
        _validate_compact_text(item, "evidence", 256)
        if "," in item:
            raise ReviewerScarError("evidence must not contain commas")


def _normalized_signal(value: str) -> str:
    return value.strip().casefold().replace("_", "-")


def _record_mapping(record: ScarRecord) -> dict[str, Any]:
    return {
        "scar_id": record.scar_id,
        "pack": record.pack.value,
        "kind": record.kind.value,
        "scope": record.scope,
        "condition": record.condition,
        "rule": record.rule,
        "state": record.state.value,
        "prevention": record.prevention.value,
        "evidence": list(record.evidence),
        "history": [state.value for state in record.history],
    }


def _record_from_mapping(value: object) -> ScarRecord:
    if not isinstance(value, dict):
        raise ReviewerScarError("reviewer scar record must be an object")
    record_data = cast(dict[str, Any], value)
    required = {
        "scar_id",
        "pack",
        "kind",
        "scope",
        "condition",
        "rule",
        "state",
        "prevention",
        "evidence",
        "history",
    }
    if set(record_data) != required:
        raise ReviewerScarError("reviewer scar record fields are invalid")
    scar_id = _safe_field(record_data["scar_id"], "scar_id")
    scope = _safe_field(record_data["scope"], "scope")
    condition = _safe_field(record_data["condition"], "condition")
    rule = _safe_field(record_data["rule"], "rule")
    evidence_raw = record_data["evidence"]
    history_raw = record_data["history"]
    if not isinstance(evidence_raw, list) or not all(
        isinstance(item, str) for item in evidence_raw
    ):
        raise ReviewerScarError("reviewer scar evidence must be an array")
    _validate_evidence(evidence_raw)
    if not isinstance(history_raw, list) or not all(
        isinstance(item, str) for item in history_raw
    ):
        raise ReviewerScarError("reviewer scar history must be an array")
    history = tuple(ScarState(item) for item in history_raw)
    record = ScarRecord(
        scar_id=scar_id,
        pack=ReviewerPack(record_data["pack"]),
        kind=ScarKind(record_data["kind"]),
        scope=scope,
        condition=condition,
        rule=rule,
        state=ScarState(record_data["state"]),
        prevention=PreventionClass(record_data["prevention"]),
        evidence=tuple(cast(list[str], evidence_raw)),
        history=history,
    )
    expected = _scar_id(
        pack=record.pack,
        kind=record.kind,
        scope=record.scope,
        condition=record.condition,
        rule=record.rule,
    )
    if record.scar_id != expected:
        raise ReviewerScarError("reviewer scar id does not match its semantic key")
    return record


__all__ = [
    "ExitStatus",
    "PreventionClass",
    "ReviewerPack",
    "ReviewerScarError",
    "ScarCandidate",
    "ScarDecision",
    "ScarKind",
    "ScarRecord",
    "ScarRegistry",
    "ScarSelection",
    "ScarState",
    "SubagentExitTicket",
    "TaskFingerprint",
    "VerificationLevel",
    "admit_scar_candidate",
    "resolve_enabled_packs",
    "select_reviewer_packs",
    "select_scars_for_context",
]
