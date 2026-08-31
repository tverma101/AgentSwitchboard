"""Contracts for the minimal Claude automatic-compaction receipt."""

import json
from pathlib import Path
from typing import Any

import pytest

from smoke.lib.auto_compact_receipt import (
    AutoCompactReceiptError,
    evidence_kind,
    validate_live_auto_compact_receipt,
)

ROOT = Path(__file__).parents[2]


def _load(relative_path: str) -> dict[str, Any]:
    """Load dynamic JSON fixture data at the test boundary."""

    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_synthetic_contract_fixture_cannot_be_used_as_live_evidence() -> None:
    receipt = _load("smoke/fixtures/claude-auto-compact-contract.json")

    assert evidence_kind(receipt) == "synthetic_contract"
    with pytest.raises(AutoCompactReceiptError, match="cannot satisfy"):
        validate_live_auto_compact_receipt(receipt)
