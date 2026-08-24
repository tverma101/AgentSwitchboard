"""Deterministic Claude candidate promotion and rollback contracts.

This module is deliberately separate from the shipped Claude compatibility
firewall. Candidate evaluation is pure: it returns a new assessment and never
changes the known-good version, route, filesystem, or user configuration.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast

from .diagnostics import redact_sensitive_error_text

CandidateLifecycle = Literal[
    "known_good",
    "candidate",
    "certified",
    "quarantined",
    "rolled_back",
]

_VERSION_RE = re.compile(r"\b(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)\b")
_EVIDENCE_MAX_BYTES = 2_048


class ClaudeCandidateError(RuntimeError):
    """A candidate transition would violate the release contract."""


@dataclass(frozen=True, slots=True)
class ClaudeCandidateProcess:
    """Metadata returned by a fake or bounded candidate process probe."""

    exit_code: int
    version_output: str
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True, slots=True)
class ClaudeCandidateEvidence:
    """One bounded, sanitized reason for candidate certification failure."""

    code: str
    detail: str

    def as_receipt(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ClaudeReleaseState:
    """Immutable active/last-known-good routing state for a canary."""

    last_known_good_version: str
    last_known_good_route: str
    active_version: str
    active_route: str
    candidate_version: str | None = None
    candidate_route: str | None = None
    candidate_state: CandidateLifecycle = "known_good"

    def as_receipt(self) -> dict[str, object]:
        """Return state metadata without candidate process or config content."""

        return {
            "schema_version": 1,
            "last_known_good_version": self.last_known_good_version,
            "last_known_good_route": _sanitize(self.last_known_good_route),
            "active_version": self.active_version,
            "active_route": _sanitize(self.active_route),
            "candidate_version": self.candidate_version,
            "candidate_route": (
                _sanitize(self.candidate_route)
                if self.candidate_route is not None
                else None
            ),
            "candidate_state": self.candidate_state,
        }


@dataclass(frozen=True, slots=True)
class ClaudeCandidateAssessment:
    """Pure result of evaluating one candidate against known-good metadata."""

    candidate_version: str | None
    candidate_route: str | None
    state: Literal["certified", "quarantined"]
    active_version: str
    active_route: str
    last_known_good_version: str
    last_known_good_route: str
    evidence: tuple[ClaudeCandidateEvidence, ...] = ()

    @property
    def certified(self) -> bool:
        return self.state == "certified"

    def as_receipt(self) -> dict[str, object]:
        """Return a metadata-only candidate assessment receipt."""

        return {
            "schema_version": 1,
            "candidate_version": self.candidate_version,
            "candidate_route": (
                _sanitize(self.candidate_route)
                if self.candidate_route is not None
                else None
            ),
            "state": self.state,
            "active_version": self.active_version,
            "active_route": _sanitize(self.active_route),
            "last_known_good_version": self.last_known_good_version,
            "last_known_good_route": _sanitize(self.last_known_good_route),
            "evidence": [item.as_receipt() for item in self.evidence],
        }


def initial_claude_release_state(
    *, last_known_good_version: str, last_known_good_route: str
) -> ClaudeReleaseState:
    """Create an explicit state whose active route is known-good."""

    _require_non_empty(last_known_good_version, "last-known-good version")
    _require_non_empty(last_known_good_route, "last-known-good route")
    return ClaudeReleaseState(
        last_known_good_version=last_known_good_version,
        last_known_good_route=last_known_good_route,
        active_version=last_known_good_version,
        active_route=last_known_good_route,
    )


def stage_claude_candidate(
    state: ClaudeReleaseState, *, version: str, route: str
) -> ClaudeReleaseState:
    """Stage a newer candidate without changing active or known-good routing."""

    _require_non_empty(version, "candidate version")
    _require_non_empty(route, "candidate route")
    if _version_tuple(version) <= _version_tuple(state.last_known_good_version):
        raise ClaudeCandidateError(
            "Claude candidate must be newer than the explicit last-known-good version"
        )
    return replace(
        state,
        candidate_version=version,
        candidate_route=route,
        candidate_state="candidate",
    )


def assess_claude_candidate(
    state: ClaudeReleaseState,
    *,
    known_good_metadata: Mapping[str, object],
    candidate_metadata: Mapping[str, object],
    process: ClaudeCandidateProcess,
) -> ClaudeCandidateAssessment:
    """Certify or quarantine a fake candidate process against known-good data.

    The contract compares only fields already present in the known-good
    ``contract`` mapping. New candidate fields are additive and therefore safe;
    changing or removing an established field is a semantic contract change.
    """

    candidate_version = _string_field(candidate_metadata, "version")
    candidate_route = _string_field(candidate_metadata, "route")
    evidence: list[ClaudeCandidateEvidence] = []

    known_good_version = _string_field(known_good_metadata, "version")
    if known_good_version != state.last_known_good_version:
        evidence.append(
            _evidence(
                "known_good_version_mismatch",
                f"metadata={known_good_version or 'missing'}; "
                f"state={state.last_known_good_version}",
            )
        )
    known_good_route = _string_field(known_good_metadata, "route")
    if known_good_route != state.last_known_good_route:
        evidence.append(
            _evidence(
                "known_good_route_mismatch",
                f"metadata={known_good_route or 'missing'}; "
                f"state={state.last_known_good_route}",
            )
        )

    if candidate_version is None:
        evidence.append(_evidence("candidate_version_missing", "version is absent"))
    elif _version_tuple(candidate_version) <= _version_tuple(
        state.last_known_good_version
    ):
        evidence.append(
            _evidence(
                "candidate_not_newer",
                f"candidate version {candidate_version} is not newer than "
                f"last-known-good {state.last_known_good_version}",
            )
        )
    if candidate_route is None:
        evidence.append(_evidence("candidate_route_missing", "route is absent"))

    reported_version = _version_from_text(process.version_output)
    if process.exit_code != 0:
        evidence.append(
            _evidence(
                "candidate_process_failed",
                f"exit_code={process.exit_code}; {_process_output(process)}",
            )
        )
    elif reported_version is None:
        evidence.append(
            _evidence(
                "candidate_version_unparseable",
                f"version output did not contain a semantic version; "
                f"{_process_output(process)}",
            )
        )
    elif candidate_version is not None and reported_version != candidate_version:
        evidence.append(
            _evidence(
                "candidate_version_mismatch",
                f"metadata={candidate_version}; process={reported_version}",
            )
        )

    evidence.extend(_contract_differences(known_good_metadata, candidate_metadata))
    state_name: Literal["certified", "quarantined"] = (
        "certified" if not evidence else "quarantined"
    )
    return ClaudeCandidateAssessment(
        candidate_version=candidate_version,
        candidate_route=candidate_route,
        state=state_name,
        active_version=state.active_version,
        active_route=state.active_route,
        last_known_good_version=state.last_known_good_version,
        last_known_good_route=state.last_known_good_route,
        evidence=tuple(evidence),
    )


def record_claude_candidate(
    state: ClaudeReleaseState, assessment: ClaudeCandidateAssessment
) -> ClaudeReleaseState:
    """Record assessment state while preserving the current active route."""

    _require_assessment_matches_state(state, assessment)
    return replace(
        state,
        candidate_version=assessment.candidate_version,
        candidate_route=assessment.candidate_route,
        candidate_state=assessment.state,
    )


def promote_claude_candidate(state: ClaudeReleaseState) -> ClaudeReleaseState:
    """Explicitly route to a certified candidate; no implicit promotion occurs."""

    if state.candidate_state != "certified":
        raise ClaudeCandidateError(
            "Claude candidate must be certified before explicit promotion"
        )
    if state.candidate_version is None or state.candidate_route is None:
        raise ClaudeCandidateError("certified Claude candidate has no route")
    return replace(
        state,
        active_version=state.candidate_version,
        active_route=state.candidate_route,
    )


def rollback_claude_candidate(state: ClaudeReleaseState) -> ClaudeReleaseState:
    """Restore the explicit last-known-good version and route."""

    return replace(
        state,
        active_version=state.last_known_good_version,
        active_route=state.last_known_good_route,
        candidate_state="rolled_back",
    )


def _contract_differences(
    known_good_metadata: Mapping[str, object],
    candidate_metadata: Mapping[str, object],
) -> list[ClaudeCandidateEvidence]:
    known_good_contract = _object_mapping(known_good_metadata.get("contract"))
    candidate_contract = _object_mapping(candidate_metadata.get("contract"))
    if known_good_contract is None:
        return [_evidence("known_good_contract_missing", "contract is absent")]
    if candidate_contract is None:
        return [_evidence("candidate_contract_missing", "contract is absent")]

    evidence: list[ClaudeCandidateEvidence] = []
    for field_name, expected in known_good_contract.items():
        if field_name not in candidate_contract:
            evidence.append(
                _evidence(
                    "semantic_contract_changed",
                    f"field={field_name}; candidate field is missing",
                )
            )
            continue
        try:
            expected_value = _canonical_json_value(expected)
            candidate_value = _canonical_json_value(candidate_contract[field_name])
        except TypeError:
            evidence.append(
                _evidence(
                    "semantic_contract_changed",
                    f"field={field_name}; contract value is not JSON-compatible",
                )
            )
            continue
        if expected_value != candidate_value:
            evidence.append(
                _evidence(
                    "semantic_contract_changed",
                    f"field={field_name}; expected={_safe_json(expected_value)}; "
                    f"observed={_safe_json(candidate_value)}",
                )
            )
    return evidence


def _canonical_json_value(value: object) -> object:
    mapping = _object_mapping(value)
    if mapping is not None:
        return {
            key: _canonical_json_value(item)
            for key, item in sorted(mapping.items(), key=lambda item: item[0])
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(type(value).__name__)


def _string_field(metadata: Mapping[str, object], name: str) -> str | None:
    value = metadata.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _require_non_empty(value: str, label: str) -> None:
    if not value.strip():
        raise ClaudeCandidateError(f"{label} must not be empty")


def _require_assessment_matches_state(
    state: ClaudeReleaseState, assessment: ClaudeCandidateAssessment
) -> None:
    if (
        assessment.last_known_good_version != state.last_known_good_version
        or assessment.last_known_good_route != state.last_known_good_route
        or assessment.active_version != state.active_version
        or assessment.active_route != state.active_route
        or (
            state.candidate_version is not None
            and assessment.candidate_version != state.candidate_version
        )
        or (
            state.candidate_route is not None
            and assessment.candidate_route != state.candidate_route
        )
    ):
        raise ClaudeCandidateError(
            "Claude candidate assessment does not belong to the current release state"
        )


def _evidence(code: str, detail: str) -> ClaudeCandidateEvidence:
    return ClaudeCandidateEvidence(code=code, detail=_sanitize(detail))


def _process_output(process: ClaudeCandidateProcess) -> str:
    output = process.stderr.strip() or process.stdout.strip()
    return _sanitize(output) if output else "no process output"


def _safe_json(value: object) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        encoded = repr(value)
    return _sanitize(encoded)


def _sanitize(value: str) -> str:
    sanitized = redact_sensitive_error_text(value)
    encoded = sanitized.encode("utf-8", errors="replace")
    if len(encoded) <= _EVIDENCE_MAX_BYTES:
        return sanitized
    return encoded[:_EVIDENCE_MAX_BYTES].decode("utf-8", errors="replace") + (
        "\n... [truncated]"
    )


def _version_from_text(value: str) -> str | None:
    match = _VERSION_RE.search(value)
    return match.group(0) if match else None


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        return (0, 0, 0)
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


__all__ = [
    "ClaudeCandidateAssessment",
    "ClaudeCandidateError",
    "ClaudeCandidateEvidence",
    "ClaudeCandidateProcess",
    "ClaudeReleaseState",
    "assess_claude_candidate",
    "initial_claude_release_state",
    "promote_claude_candidate",
    "record_claude_candidate",
    "rollback_claude_candidate",
    "stage_claude_candidate",
]
