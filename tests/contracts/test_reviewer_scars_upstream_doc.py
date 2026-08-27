"""Keep the reviewer-scar parts-bin provenance exact and reviewable."""

from pathlib import Path


def test_reviewer_scar_upstream_pin_and_license_are_documented() -> None:
    text = Path("docs/REVIEWER_SCARS_UPSTREAMS.md").read_text("utf-8")

    assert "letta-ai/letta-code" in text
    assert "b94afce3a9e57fec042c27bc6fb43c43e27c7774" in text
    assert "Apache License 2.0" in text
    assert "does **not** import another memory runtime" in text
