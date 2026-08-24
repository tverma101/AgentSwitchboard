"""Contracts for the minimal Claude automatic-compaction receipt."""

import json
from pathlib import Path

import pytest

from smoke.lib.auto_compact_receipt import (
    AutoCompactReceiptError,
    evidence_kind,
    validate_live_auto_compact_receipt,
)

ROOT = Path(__file__).parents[2]


def _load(relative_path: str) -> dict[str, object]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_checked_in_muse_receipt_proves_only_the_minimal_live_gate() -> None:
    receipt = _load("smoke/receipts/muse-auto-compact-2026-08-24.json")

    summary = validate_live_auto_compact_receipt(receipt)

    assert summary["evidence_kind"] == "live_installed_claude"
    assert summary["requested_context_tokens"] == 50_000
    assert summary["effective_context_tokens"] == 50_000
    boundaries = summary["unverified_boundaries"]
    assert isinstance(boundaries, tuple)
    assert "harness_commit_sha_at_capture" in boundaries


def test_synthetic_contract_fixture_cannot_be_used_as_live_evidence() -> None:
    receipt = _load("smoke/fixtures/claude-auto-compact-contract.json")

    assert evidence_kind(receipt) == "synthetic_contract"
    with pytest.raises(AutoCompactReceiptError, match="cannot satisfy"):
        validate_live_auto_compact_receipt(receipt)


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    (
        (
            ("compaction", "trigger"),
            "manual",
            "compaction.trigger",
        ),
        (
            ("compaction", "compact_boundary_observed"),
            False,
            "compaction.compact_boundary_observed",
        ),
        (
            ("context", "effective_tokens"),
            60_000,
            "context.effective_tokens",
        ),
    ),
)
def test_live_receipt_rejects_non_conformant_claims(
    path: tuple[str, str], replacement: object, message: str
) -> None:
    receipt = _load("smoke/receipts/muse-auto-compact-2026-08-24.json")
    section, field = path
    section_value = receipt[section]
    assert isinstance(section_value, dict)
    section_value[field] = replacement

    with pytest.raises(AutoCompactReceiptError, match=message):
        validate_live_auto_compact_receipt(receipt)


def test_live_receipt_rejects_payload_bearing_fields() -> None:
    receipt = _load("smoke/receipts/muse-auto-compact-2026-08-24.json")
    receipt["telemetry"] = {"metadata_only": True, "prompt": "omitted"}

    with pytest.raises(AutoCompactReceiptError, match="content-bearing"):
        validate_live_auto_compact_receipt(receipt)
