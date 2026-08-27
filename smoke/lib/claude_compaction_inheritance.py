"""Metadata-only deterministic contracts for Claude policy inheritance."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

INHERITANCE_SCHEMA = "fcc.claude-compaction-inheritance.v1"
INHERITANCE_EVIDENCE = "synthetic-only"
INHERITANCE_SURFACES = (
    "resumed_session",
    "forked_session",
    "subagent_after_compaction",
    "child_process_after_compaction",
    "interrupted_compaction_recovery",
    "candidate_upgrade",
)

_ALLOWED_STATUSES = frozenset({"passed", "unverified", "skipped"})
_ALLOWED_COMPACT_STATES = frozenset(
    {"not_exercised", "armed", "fired", "recovered", "interrupted"}
)
_ALLOWED_CONTINUATIONS = frozenset(
    {"not_applicable", "not_observed", "continued", "blocked"}
)
_ALLOWED_POLICY_SOURCES = frozenset({"fcc", "explicit_user_override"})
_ALLOWED_CERTIFICATION = frozenset(
    {"not_applicable", "certified", "quarantined", "not_run"}
)
_ALLOWED_RECOVERY_ACTIONS = frozenset({"none", "resume", "quarantine"})
_RAW_FIELDS = frozenset(
    {
        "api_key",
        "arguments",
        "content",
        "credential",
        "encrypted_content",
        "image",
        "messages",
        "prompt",
        "raw_request",
        "raw_response",
        "response",
        "session_content",
        "text",
        "tool_result",
    }
)
_OBSERVATION_FIELDS = frozenset(
    {
        "surface",
        "status",
        "parent_version",
        "child_version",
        "requested_context_tokens",
        "effective_context_tokens",
        "requested_compact_window_tokens",
        "effective_compact_window_tokens",
        "inherited_policy_hash",
        "effective_policy_hash",
        "gateway_identity",
        "provider_model_ref",
        "upstream_protocol",
        "route_identity",
        "relationship_hash",
        "compact_state",
        "continuation",
        "policy_source",
        "override_context_tokens",
        "certification",
        "recovery_action",
        "reason",
    }
)
_MATRIX_FIELDS = frozenset(
    {
        "schema",
        "receipt",
        "evidence",
        "live_provider_claim",
        "required_surfaces",
        "baseline",
        "surfaces",
        "passed",
        "invariants",
        "status_summary",
    }
)
_CHILD_SURFACES = frozenset(
    {
        "resumed_session",
        "forked_session",
        "subagent_after_compaction",
        "child_process_after_compaction",
        "candidate_upgrade",
    }
)
_MIN_CONTEXT_TOKENS = 32_000
_MAX_CONTEXT_TOKENS = 1_000_000


class CompactionInheritanceError(ValueError):
    """A compaction inheritance receipt cannot prove its required invariants."""


@dataclass(frozen=True, slots=True)
class InheritanceObservation:
    """Sanitized policy and lifecycle metadata for one execution surface."""

    surface: str
    status: str
    parent_version: str
    child_version: str
    requested_context_tokens: int
    effective_context_tokens: int | None
    requested_compact_window_tokens: int
    effective_compact_window_tokens: int | None
    inherited_policy_hash: str | None
    effective_policy_hash: str | None
    gateway_identity: str | None
    provider_model_ref: str | None
    upstream_protocol: str | None
    route_identity: str | None
    relationship_hash: str | None
    compact_state: str
    continuation: str
    policy_source: str | None
    override_context_tokens: int | None = None
    certification: str = "not_applicable"
    recovery_action: str = "none"
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("surface", "parent_version", "child_version"):
            _require_text(getattr(self, name), name)
        if self.status not in _ALLOWED_STATUSES:
            raise ValueError(f"unsupported inheritance status: {self.status!r}")
        for name in (
            "requested_context_tokens",
            "requested_compact_window_tokens",
        ):
            _bounded_context(getattr(self, name), name)
        for name in ("effective_context_tokens", "effective_compact_window_tokens"):
            _optional_bounded_context(getattr(self, name), name)
        for name in (
            "inherited_policy_hash",
            "effective_policy_hash",
            "gateway_identity",
            "provider_model_ref",
            "upstream_protocol",
            "route_identity",
            "relationship_hash",
            "policy_source",
            "reason",
        ):
            _optional_text(getattr(self, name), name)
        if self.compact_state not in _ALLOWED_COMPACT_STATES:
            raise ValueError(f"unsupported compaction state: {self.compact_state!r}")
        if self.continuation not in _ALLOWED_CONTINUATIONS:
            raise ValueError(f"unsupported continuation state: {self.continuation!r}")
        if (
            self.policy_source is not None
            and self.policy_source not in _ALLOWED_POLICY_SOURCES
        ):
            raise ValueError(f"unsupported policy source: {self.policy_source!r}")
        if self.certification not in _ALLOWED_CERTIFICATION:
            raise ValueError(f"unsupported certification state: {self.certification!r}")
        if self.recovery_action not in _ALLOWED_RECOVERY_ACTIONS:
            raise ValueError(
                f"unsupported compaction recovery action: {self.recovery_action!r}"
            )
        if self.override_context_tokens is not None:
            _bounded_context(self.override_context_tokens, "override_context_tokens")
            if self.policy_source != "explicit_user_override":
                raise ValueError(
                    "override_context_tokens requires explicit_user_override"
                )
        if self.policy_source == "explicit_user_override" and (
            self.override_context_tokens is None
        ):
            raise ValueError("explicit_user_override requires override_context_tokens")
        if self.status != "passed" and not self.reason:
            raise ValueError("unverified or skipped observations require a reason")

    def as_receipt(self) -> dict[str, Any]:
        """Serialize only versions, hashes, counts, states, and statuses."""

        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> InheritanceObservation:
        """Parse one metadata-only observation and reject unknown state fields."""

        if not isinstance(value, Mapping):
            raise ValueError("inheritance observation must be a metadata mapping")
        _reject_fields(value, _OBSERVATION_FIELDS, "inheritance observation")
        return cls(
            surface=_required_text(value, "surface"),
            status=_required_text(value, "status"),
            parent_version=_required_text(value, "parent_version"),
            child_version=_required_text(value, "child_version"),
            requested_context_tokens=_positive_int(
                value.get("requested_context_tokens"), "requested_context_tokens"
            ),
            effective_context_tokens=_optional_bounded_context(
                value.get("effective_context_tokens"), "effective_context_tokens"
            ),
            requested_compact_window_tokens=_positive_int(
                value.get("requested_compact_window_tokens"),
                "requested_compact_window_tokens",
            ),
            effective_compact_window_tokens=_optional_bounded_context(
                value.get("effective_compact_window_tokens"),
                "effective_compact_window_tokens",
            ),
            inherited_policy_hash=_optional_text(
                value.get("inherited_policy_hash"), "inherited_policy_hash"
            ),
            effective_policy_hash=_optional_text(
                value.get("effective_policy_hash"), "effective_policy_hash"
            ),
            gateway_identity=_optional_text(
                value.get("gateway_identity"), "gateway_identity"
            ),
            provider_model_ref=_optional_text(
                value.get("provider_model_ref"), "provider_model_ref"
            ),
            upstream_protocol=_optional_text(
                value.get("upstream_protocol"), "upstream_protocol"
            ),
            route_identity=_optional_text(
                value.get("route_identity"), "route_identity"
            ),
            relationship_hash=_optional_text(
                value.get("relationship_hash"), "relationship_hash"
            ),
            compact_state=_required_text(value, "compact_state"),
            continuation=_required_text(value, "continuation"),
            policy_source=_optional_text(value.get("policy_source"), "policy_source"),
            override_context_tokens=_optional_positive_int(
                value.get("override_context_tokens"), "override_context_tokens"
            ),
            certification=_required_text_or_default(
                value, "certification", "not_applicable"
            ),
            recovery_action=_required_text_or_default(value, "recovery_action", "none"),
            reason=_optional_text(value.get("reason"), "reason"),
        )


def validate_inheritance_matrix(
    baseline: InheritanceObservation,
    surfaces: Sequence[InheritanceObservation],
    *,
    required_surfaces: Sequence[str] = INHERITANCE_SURFACES,
) -> dict[str, Any]:
    """Return a deterministic gate for resumable and child execution surfaces."""

    rows = tuple(surfaces)
    required = tuple(required_surfaces)
    names = (baseline.surface, *(row.surface for row in rows))
    by_name = {row.surface: row for row in rows}
    invariants = {
        "baseline_established": _baseline_is_valid(baseline),
        "surface_names_unique": len(names) == len(set(names)),
        "required_surfaces_present": set(required).issubset(by_name),
        "passed_boundaries_reassert_policy": all(
            _policy_reasserted(baseline, row) for row in rows
        ),
        "passed_boundaries_reassert_route": all(
            _route_reasserted(baseline, row) for row in rows
        ),
        "passed_boundaries_have_relationship_hash": all(
            row.status != "passed"
            or row.surface not in _CHILD_SURFACES
            or bool(row.relationship_hash)
            for row in rows
        ),
        "compact_continuations_are_complete": all(
            _compact_continuation_is_complete(row) for row in rows
        ),
        "interrupted_compaction_fails_closed": _interrupted_compaction_is_safe(
            by_name.get("interrupted_compaction_recovery")
        ),
        "candidate_versions_certified_or_quarantined": _candidate_upgrade_is_safe(
            by_name.get("candidate_upgrade")
        ),
        "explicit_overrides_bounded_and_visible": all(
            _override_is_visible(row) for row in rows
        ),
        "unverified_boundaries_are_labeled": all(
            row.status == "passed" or bool(row.reason) for row in rows
        ),
        "first_party_route_not_claimed": all(
            not _is_first_party_route(row.route_identity) for row in (baseline, *rows)
        ),
    }
    return {
        "schema": INHERITANCE_SCHEMA,
        "evidence": INHERITANCE_EVIDENCE,
        "live_provider_claim": False,
        "required_surfaces": list(required),
        "passed": all(invariants.values()),
        "invariants": invariants,
        "baseline": baseline.as_receipt(),
        "surfaces": [row.as_receipt() for row in rows],
        "status_summary": {
            baseline.surface: baseline.status,
            **{row.surface: row.status for row in rows},
        },
    }


def assert_inheritance_matrix(
    baseline: InheritanceObservation,
    surfaces: Sequence[InheritanceObservation],
    *,
    required_surfaces: Sequence[str] = INHERITANCE_SURFACES,
) -> dict[str, Any]:
    """Validate the matrix and raise with failed invariant names."""

    receipt = validate_inheritance_matrix(
        baseline,
        surfaces,
        required_surfaces=required_surfaces,
    )
    if not receipt["passed"]:
        failed = [name for name, passed in receipt["invariants"].items() if not passed]
        raise CompactionInheritanceError(
            "compaction inheritance failed: " + ", ".join(failed)
        )
    return receipt


def load_inheritance_receipt(
    path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate one checked-in synthetic inheritance receipt."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid compaction inheritance receipt: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("compaction inheritance receipt must be an object")
    _reject_fields(payload, _MATRIX_FIELDS, "compaction inheritance receipt")
    if payload.get("schema") != INHERITANCE_SCHEMA:
        raise ValueError("unexpected compaction inheritance receipt schema")
    if payload.get("evidence") != INHERITANCE_EVIDENCE:
        raise ValueError("compaction inheritance receipt must be synthetic-only")
    if payload.get("live_provider_claim") is not False:
        raise ValueError("synthetic inheritance receipt cannot claim live providers")
    baseline_value = payload.get("baseline")
    surfaces_value = payload.get("surfaces")
    if not isinstance(baseline_value, Mapping):
        raise ValueError("compaction inheritance receipt baseline must be an object")
    if not isinstance(surfaces_value, Sequence) or isinstance(
        surfaces_value, str | bytes | bytearray
    ):
        raise ValueError("compaction inheritance receipt surfaces must be an array")
    if not all(isinstance(item, Mapping) for item in surfaces_value):
        raise ValueError("compaction inheritance receipt surfaces must be objects")
    required = _required_string_list(payload, "required_surfaces")
    baseline = InheritanceObservation.from_mapping(baseline_value)
    surfaces = tuple(
        InheritanceObservation.from_mapping(item) for item in surfaces_value
    )
    receipt = assert_inheritance_matrix(
        baseline,
        surfaces,
        required_surfaces=required,
    )
    if payload.get("passed") != receipt["passed"]:
        raise ValueError("inheritance receipt passed flag does not match its gate")
    if payload.get("invariants") != receipt["invariants"]:
        raise ValueError("inheritance receipt invariants do not match its gate")
    if payload.get("status_summary") != receipt["status_summary"]:
        raise ValueError("inheritance receipt status summary does not match its gate")
    return dict(payload), receipt


def _baseline_is_valid(baseline: InheritanceObservation) -> bool:
    return (
        baseline.surface == "fresh_session"
        and baseline.status == "passed"
        and baseline.effective_context_tokens is not None
        and baseline.effective_compact_window_tokens is not None
        and baseline.requested_context_tokens == baseline.effective_context_tokens
        and baseline.requested_compact_window_tokens
        == baseline.effective_compact_window_tokens
        and bool(baseline.effective_policy_hash)
        and bool(baseline.gateway_identity)
        and bool(baseline.provider_model_ref)
        and bool(baseline.upstream_protocol)
        and bool(baseline.route_identity)
        and bool(baseline.relationship_hash)
        and baseline.policy_source == "fcc"
    )


def _policy_reasserted(
    baseline: InheritanceObservation,
    row: InheritanceObservation,
) -> bool:
    if row.status != "passed":
        return True
    if (
        baseline.effective_context_tokens is None
        or baseline.effective_compact_window_tokens is None
        or baseline.effective_policy_hash is None
    ):
        return False
    if row.inherited_policy_hash != baseline.effective_policy_hash:
        return False
    override = row.override_context_tokens
    if override is not None:
        return (
            row.policy_source == "explicit_user_override"
            and row.requested_context_tokens == override
            and row.effective_context_tokens == override
            and row.requested_compact_window_tokens == override
            and row.effective_compact_window_tokens == override
            and row.effective_policy_hash != baseline.effective_policy_hash
        )
    return (
        row.policy_source == "fcc"
        and row.requested_context_tokens == baseline.effective_context_tokens
        and row.effective_context_tokens == baseline.effective_context_tokens
        and row.requested_compact_window_tokens
        == baseline.effective_compact_window_tokens
        and row.effective_compact_window_tokens
        == baseline.effective_compact_window_tokens
        and row.effective_policy_hash == baseline.effective_policy_hash
    )


def _route_reasserted(
    baseline: InheritanceObservation,
    row: InheritanceObservation,
) -> bool:
    return row.status != "passed" or (
        bool(baseline.gateway_identity)
        and row.gateway_identity == baseline.gateway_identity
        and bool(baseline.provider_model_ref)
        and row.provider_model_ref == baseline.provider_model_ref
        and bool(baseline.upstream_protocol)
        and row.upstream_protocol == baseline.upstream_protocol
        and bool(baseline.route_identity)
        and row.route_identity == baseline.route_identity
        and not _is_first_party_route(row.route_identity)
    )


def _compact_continuation_is_complete(row: InheritanceObservation) -> bool:
    if row.status != "passed":
        return True
    if row.compact_state == "interrupted":
        return False
    if row.compact_state in {"fired", "recovered"}:
        return row.continuation == "continued"
    return row.continuation != "blocked"


def _interrupted_compaction_is_safe(row: InheritanceObservation | None) -> bool:
    return row is not None and (
        row.status in {"unverified", "skipped"}
        and row.compact_state == "interrupted"
        and row.continuation != "continued"
        and row.recovery_action == "quarantine"
    )


def _candidate_upgrade_is_safe(row: InheritanceObservation | None) -> bool:
    if row is None:
        return False
    if row.status == "passed":
        return (
            row.parent_version != row.child_version and row.certification == "certified"
        )
    return row.certification in {"not_run", "quarantined"} and (
        row.recovery_action == "quarantine"
    )


def _override_is_visible(row: InheritanceObservation) -> bool:
    if row.override_context_tokens is None:
        return row.policy_source != "explicit_user_override"
    return (
        _MIN_CONTEXT_TOKENS <= row.override_context_tokens <= _MAX_CONTEXT_TOKENS
        and row.policy_source == "explicit_user_override"
        and row.requested_context_tokens == row.override_context_tokens
        and row.effective_context_tokens == row.override_context_tokens
        and row.requested_compact_window_tokens == row.override_context_tokens
        and row.effective_compact_window_tokens == row.override_context_tokens
    )


def _is_first_party_route(value: str | None) -> bool:
    if value is None:
        return False
    normalized = "".join(
        character for character in value.casefold() if character.isalnum()
    )
    return "firstparty" in normalized


def _reject_fields(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    leaked = sorted(_RAW_FIELDS.intersection(value), key=str)
    if leaked:
        raise ValueError(f"{label} must be metadata-only; forbidden fields: {leaked}")
    unsupported = sorted((key for key in value if key not in allowed), key=str)
    if unsupported:
        raise ValueError(
            f"unsupported {label} fields: " + ", ".join(str(key) for key in unsupported)
        )


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _required_text(value: Mapping[str, Any], name: str) -> str:
    return _require_text(value.get(name), name)


def _required_text_or_default(value: Mapping[str, Any], name: str, default: str) -> str:
    return _require_text(value.get(name, default), name)


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name)


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, name)


def _optional_bounded_context(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _bounded_context(value, name)


def _bounded_context(value: int, name: str) -> int:
    _positive_int(value, name)
    if not _MIN_CONTEXT_TOKENS <= value <= _MAX_CONTEXT_TOKENS:
        raise ValueError(
            f"{name} must be between {_MIN_CONTEXT_TOKENS} and {_MAX_CONTEXT_TOKENS}"
        )
    return value


def _required_string_list(value: Mapping[str, Any], name: str) -> tuple[str, ...]:
    raw = value.get(name)
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes | bytearray):
        raise ValueError(f"{name} must be an array of strings")
    result = tuple(_require_text(item, f"{name} item") for item in raw)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must not contain duplicates")
    return result
