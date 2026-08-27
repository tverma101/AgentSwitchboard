"""Prevent the sweep status doc from turning deterministic work into live claims."""

from pathlib import Path


def test_open_issue_sweep_status_lists_unverified_live_boundaries() -> None:
    text = Path("docs/OPEN_ISSUE_SWEEP_STATUS.md").read_text("utf-8")

    assert "## Not claimed by this branch" in text
    assert "no live OpenCode Go/Muse success receipt" in text
    assert "no real Codex browser-plugin device pass" in text
    assert "no provider visual round-trip" in text
    assert "no automatic parent/subagent reviewer-scar integration" in text
