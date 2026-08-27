"""Deterministic tests for Claude compaction-policy inheritance receipts."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from smoke.lib.claude_compaction_inheritance import (
    CompactionInheritanceError,
    InheritanceObservation,
    assert_inheritance_matrix,
    load_inheritance_receipt,
    validate_inheritance_matrix,
)

_POLICY_HASH = "fcc-policy-50k-v1"
_GATEWAY = "synthetic-loopback"
_MODEL = "synthetic/compaction-inheritance"
_PROTOCOL = "responses"
_ROUTE = "synthetic-loopback/responses"


def _baseline() -> InheritanceObservation:
    return InheritanceObservation(
        surface="fresh_session",
        status="passed",
        parent_version="2.1.228",
        child_version="2.1.228",
        requested_context_tokens=50_000,
        effective_context_tokens=50_000,
        requested_compact_window_tokens=50_000,
        effective_compact_window_tokens=50_000,
        inherited_policy_hash=None,
        effective_policy_hash=_POLICY_HASH,
        gateway_identity=_GATEWAY,
        provider_model_ref=_MODEL,
        upstream_protocol=_PROTOCOL,
        route_identity=_ROUTE,
        relationship_hash="fresh-session-hash",
        compact_state="armed",
        continuation="not_observed",
        policy_source="fcc",
    )


def _inherited(
    surface: str,
    *,
    compact_state: str = "not_exercised",
    continuation: str = "not_observed",
    relationship_hash: str = "child-session-hash",
) -> InheritanceObservation:
    return InheritanceObservation(
        surface=surface,
        status="passed",
        parent_version="2.1.228",
        child_version="2.1.228",
        requested_context_tokens=50_000,
        effective_context_tokens=50_000,
        requested_compact_window_tokens=50_000,
        effective_compact_window_tokens=50_000,
        inherited_policy_hash=_POLICY_HASH,
        effective_policy_hash=_POLICY_HASH,
        gateway_identity=_GATEWAY,
        provider_model_ref=_MODEL,
        upstream_protocol=_PROTOCOL,
        route_identity=_ROUTE,
        relationship_hash=relationship_hash,
        compact_state=compact_state,
        continuation=continuation,
        policy_source="fcc",
    )


def _edge_rows() -> list[InheritanceObservation]:
    return [
        _inherited(
            "resumed_session",
            compact_state="fired",
            continuation="continued",
            relationship_hash="resumed-session-hash",
        ),
        _inherited("forked_session", relationship_hash="forked-session-hash"),
        InheritanceObservation(
            surface="subagent_after_compaction",
            status="unverified",
            parent_version="2.1.228",
            child_version="2.1.228",
            requested_context_tokens=50_000,
            effective_context_tokens=None,
            requested_compact_window_tokens=50_000,
            effective_compact_window_tokens=None,
            inherited_policy_hash=None,
            effective_policy_hash=None,
            gateway_identity=None,
            provider_model_ref=None,
            upstream_protocol=None,
            route_identity=None,
            relationship_hash=None,
            compact_state="not_exercised",
            continuation="not_observed",
            policy_source=None,
            reason="No bounded fixture or authorized live run crosses a subagent compact boundary.",
        ),
        InheritanceObservation(
            surface="child_process_after_compaction",
            status="unverified",
            parent_version="2.1.228",
            child_version="2.1.228",
            requested_context_tokens=50_000,
            effective_context_tokens=None,
            requested_compact_window_tokens=50_000,
            effective_compact_window_tokens=None,
            inherited_policy_hash=None,
            effective_policy_hash=None,
            gateway_identity=None,
            provider_model_ref=None,
            upstream_protocol=None,
            route_identity=None,
            relationship_hash=None,
            compact_state="not_exercised",
            continuation="not_observed",
            policy_source=None,
            reason="Child-process compaction inheritance is not exposed by the deterministic fixture.",
        ),
        InheritanceObservation(
            surface="interrupted_compaction_recovery",
            status="skipped",
            parent_version="2.1.228",
            child_version="2.1.228",
            requested_context_tokens=50_000,
            effective_context_tokens=None,
            requested_compact_window_tokens=50_000,
            effective_compact_window_tokens=None,
            inherited_policy_hash=None,
            effective_policy_hash=None,
            gateway_identity=None,
            provider_model_ref=None,
            upstream_protocol=None,
            route_identity=None,
            relationship_hash=None,
            compact_state="interrupted",
            continuation="blocked",
            policy_source=None,
            certification="not_applicable",
            recovery_action="quarantine",
            reason="No safe interruption fixture is captured; continuation remains quarantined.",
        ),
        InheritanceObservation(
            surface="candidate_upgrade",
            status="skipped",
            parent_version="2.1.228",
            child_version="candidate",
            requested_context_tokens=50_000,
            effective_context_tokens=None,
            requested_compact_window_tokens=50_000,
            effective_compact_window_tokens=None,
            inherited_policy_hash=None,
            effective_policy_hash=None,
            gateway_identity=None,
            provider_model_ref=None,
            upstream_protocol=None,
            route_identity=None,
            relationship_hash=None,
            compact_state="not_exercised",
            continuation="not_observed",
            policy_source=None,
            certification="not_run",
            recovery_action="quarantine",
            reason="No candidate Claude version was installed or authorized for a canary.",
        ),
    ]


def test_inheritance_matrix_passes_without_a_live_provider_claim() -> None:
    receipt = assert_inheritance_matrix(_baseline(), _edge_rows())

    assert receipt["schema"] == "fcc.claude-compaction-inheritance.v1"
    assert receipt["evidence"] == "synthetic-only"
    assert receipt["live_provider_claim"] is False
    assert receipt["passed"] is True
    assert all(receipt["invariants"].values())
    assert receipt["status_summary"] == {
        "fresh_session": "passed",
        "resumed_session": "passed",
        "forked_session": "passed",
        "subagent_after_compaction": "unverified",
        "child_process_after_compaction": "unverified",
        "interrupted_compaction_recovery": "skipped",
        "candidate_upgrade": "skipped",
    }
    serialized = json.dumps(receipt)
    assert "prompt" not in serialized
    assert "content" not in serialized
    assert "api_key" not in serialized


def test_subagent_compaction_case_can_pass_only_with_full_inheritance_evidence() -> (
    None
):
    rows = _edge_rows()
    rows[2] = replace(
        rows[2],
        status="passed",
        effective_context_tokens=50_000,
        effective_compact_window_tokens=50_000,
        inherited_policy_hash=_POLICY_HASH,
        effective_policy_hash=_POLICY_HASH,
        gateway_identity=_GATEWAY,
        provider_model_ref=_MODEL,
        upstream_protocol=_PROTOCOL,
        route_identity=_ROUTE,
        relationship_hash="subagent-session-hash",
        compact_state="recovered",
        continuation="continued",
        policy_source="fcc",
        reason=None,
    )

    receipt = assert_inheritance_matrix(_baseline(), rows)

    assert receipt["invariants"]["passed_boundaries_reassert_policy"] is True
    assert receipt["invariants"]["compact_continuations_are_complete"] is True


def test_child_process_compaction_case_can_pass_only_with_full_inheritance_evidence() -> (
    None
):
    rows = _edge_rows()
    rows[3] = replace(
        rows[3],
        status="passed",
        effective_context_tokens=50_000,
        effective_compact_window_tokens=50_000,
        inherited_policy_hash=_POLICY_HASH,
        effective_policy_hash=_POLICY_HASH,
        gateway_identity=_GATEWAY,
        provider_model_ref=_MODEL,
        upstream_protocol=_PROTOCOL,
        route_identity=_ROUTE,
        relationship_hash="child-process-session-hash",
        compact_state="recovered",
        continuation="continued",
        policy_source="fcc",
        reason=None,
    )

    receipt = assert_inheritance_matrix(_baseline(), rows)

    assert receipt["invariants"]["passed_boundaries_have_relationship_hash"] is True


@pytest.mark.parametrize(
    ("change", "failed"),
    [
        (
            lambda rows: [
                replace(
                    rows[0],
                    effective_context_tokens=256_000,
                    effective_compact_window_tokens=256_000,
                    effective_policy_hash="drifted-policy",
                ),
                *rows[1:],
            ],
            "passed_boundaries_reassert_policy",
        ),
        (
            lambda rows: [
                replace(rows[0], route_identity="firstParty"),
                *rows[1:],
            ],
            "passed_boundaries_reassert_route",
        ),
        (
            lambda rows: [
                replace(rows[0], provider_model_ref="synthetic/other-model"),
                *rows[1:],
            ],
            "passed_boundaries_reassert_route",
        ),
        (
            lambda rows: [
                replace(
                    rows[0],
                    compact_state="fired",
                    continuation="not_observed",
                ),
                *rows[1:],
            ],
            "compact_continuations_are_complete",
        ),
    ],
    ids=[
        "policy-drift",
        "first-party-route",
        "provider-model-drift",
        "missing-continuation",
    ],
)
def test_inheritance_rejects_silent_boundary_regressions(change, failed) -> None:
    receipt = validate_inheritance_matrix(_baseline(), change(_edge_rows()))

    assert receipt["passed"] is False
    assert receipt["invariants"][failed] is False
    with pytest.raises(CompactionInheritanceError, match=failed):
        assert_inheritance_matrix(_baseline(), change(_edge_rows()))


def test_explicit_user_override_is_bounded_and_visible() -> None:
    rows = _edge_rows()
    rows[0] = replace(
        rows[0],
        requested_context_tokens=64_000,
        effective_context_tokens=64_000,
        requested_compact_window_tokens=64_000,
        effective_compact_window_tokens=64_000,
        effective_policy_hash="user-policy-64k-v1",
        policy_source="explicit_user_override",
        override_context_tokens=64_000,
    )

    receipt = assert_inheritance_matrix(_baseline(), rows)

    assert receipt["invariants"]["explicit_overrides_bounded_and_visible"] is True
    assert receipt["invariants"]["passed_boundaries_reassert_policy"] is True


@pytest.mark.parametrize(
    "change",
    [
        {"override_context_tokens": 16_000},
        {"override_context_tokens": 1_000_001},
        {"override_context_tokens": 64_000, "policy_source": "fcc"},
    ],
    ids=["below-minimum", "above-maximum", "hidden-source"],
)
def test_override_metadata_cannot_hide_an_unbounded_or_implicit_change(change) -> None:
    with pytest.raises(ValueError):
        InheritanceObservation(**(_inherited("resumed_session").as_receipt() | change))


def test_interrupted_compaction_must_quarantine_continuation() -> None:
    rows = _edge_rows()
    interrupted = rows[4]
    rows[4] = replace(
        interrupted,
        status="passed",
        effective_context_tokens=50_000,
        effective_compact_window_tokens=50_000,
        inherited_policy_hash=_POLICY_HASH,
        effective_policy_hash=_POLICY_HASH,
        gateway_identity=_GATEWAY,
        provider_model_ref=_MODEL,
        upstream_protocol=_PROTOCOL,
        route_identity=_ROUTE,
        relationship_hash="interrupted-session-hash",
        continuation="continued",
        policy_source="fcc",
        recovery_action="resume",
        reason=None,
    )

    receipt = validate_inheritance_matrix(_baseline(), rows)

    assert receipt["passed"] is False
    assert receipt["invariants"]["interrupted_compaction_fails_closed"] is False
    assert receipt["invariants"]["compact_continuations_are_complete"] is False


def test_candidate_upgrade_can_pass_only_after_explicit_certification() -> None:
    rows = _edge_rows()
    rows[5] = replace(
        rows[5],
        status="passed",
        effective_context_tokens=50_000,
        effective_compact_window_tokens=50_000,
        inherited_policy_hash=_POLICY_HASH,
        effective_policy_hash=_POLICY_HASH,
        gateway_identity=_GATEWAY,
        provider_model_ref=_MODEL,
        upstream_protocol=_PROTOCOL,
        route_identity=_ROUTE,
        relationship_hash="candidate-session-hash",
        compact_state="recovered",
        continuation="continued",
        policy_source="fcc",
        certification="certified",
        recovery_action="resume",
        reason=None,
    )

    receipt = assert_inheritance_matrix(_baseline(), rows)

    assert receipt["invariants"]["candidate_versions_certified_or_quarantined"] is True


def test_candidate_upgrade_without_certification_is_not_promoted() -> None:
    rows = _edge_rows()
    rows[5] = replace(
        rows[5],
        status="passed",
        effective_context_tokens=50_000,
        effective_compact_window_tokens=50_000,
        inherited_policy_hash=_POLICY_HASH,
        effective_policy_hash=_POLICY_HASH,
        gateway_identity=_GATEWAY,
        provider_model_ref=_MODEL,
        upstream_protocol=_PROTOCOL,
        route_identity=_ROUTE,
        relationship_hash="candidate-session-hash",
        policy_source="fcc",
        certification="not_run",
        reason=None,
    )

    receipt = validate_inheritance_matrix(_baseline(), rows)

    assert receipt["passed"] is False
    assert receipt["invariants"]["candidate_versions_certified_or_quarantined"] is False


def test_checked_in_inheritance_receipt_is_metadata_only_and_explicit_about_edges() -> (
    None
):
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "receipts"
        / "claude-compaction-inheritance-2026-08-24.json"
    )
    payload, receipt = load_inheritance_receipt(path)

    assert payload["evidence"] == "synthetic-only"
    assert payload["live_provider_claim"] is False
    assert receipt["passed"] is True
    assert payload["status_summary"]["subagent_after_compaction"] == "unverified"
    assert payload["status_summary"]["interrupted_compaction_recovery"] == "skipped"
    assert payload["status_summary"]["candidate_upgrade"] == "skipped"
    serialized = json.dumps(payload)
    assert "prompt" not in serialized
    assert "content" not in serialized
    assert "api_key" not in serialized


@pytest.mark.parametrize("field", ["prompt", "content", "api_key", "raw_request"])
def test_observation_parser_rejects_content_and_credentials(field: str) -> None:
    value = _baseline().as_receipt() | {field: "must not be retained"}

    with pytest.raises(ValueError, match="metadata-only"):
        InheritanceObservation.from_mapping(value)


def test_observation_parser_rejects_unknown_state_fields() -> None:
    with pytest.raises(ValueError, match="unsupported inheritance observation fields"):
        InheritanceObservation.from_mapping(
            _baseline().as_receipt() | {"effective_prompt_hash": "not-contract"}
        )


def test_inheritance_rejects_duplicate_or_missing_surface_names() -> None:
    rows = _edge_rows()
    duplicate = [replace(rows[0], surface="forked_session"), *rows[1:]]

    duplicate_receipt = validate_inheritance_matrix(_baseline(), duplicate)
    assert duplicate_receipt["invariants"]["surface_names_unique"] is False

    missing_receipt = validate_inheritance_matrix(
        _baseline(), rows[:-1], required_surfaces=("candidate_upgrade",)
    )
    assert missing_receipt["invariants"]["required_surfaces_present"] is False


def test_baseline_rejects_requested_effective_policy_drift() -> None:
    baseline = replace(_baseline(), effective_context_tokens=256_000)

    receipt = validate_inheritance_matrix(baseline, _edge_rows())

    assert receipt["passed"] is False
    assert receipt["invariants"]["baseline_established"] is False
