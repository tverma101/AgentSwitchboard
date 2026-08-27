from pathlib import Path


def test_sweep_commands_use_shared_entrypoints() -> None:
    text = Path("docs/OPEN_ISSUE_SWEEP_COMMANDS.md").read_text("utf-8")
    assert "scripts/certify_open_issues.py" in text
    assert "scripts/smoke_codex_browser.py" in text
    assert "scripts/compare_native_harness.py" in text
    assert "does not certify a live provider" in text
