"""Validate the checked-in native/Harness comparator example."""

import json
from pathlib import Path

from smoke.lib.native_harness_comparator import PathObservation, compare_paths


def test_comparator_example_is_valid_and_successful() -> None:
    value = json.loads(
        Path("smoke/fixtures/native-harness-comparator-example.json").read_text("utf-8")
    )

    receipt = compare_paths(
        PathObservation.from_mapping(value["native"]),
        PathObservation.from_mapping(value["harness"]),
    )

    assert receipt["attribution"]["fault_domain"] is None
    assert receipt["comparison"]["success_match"] is True
