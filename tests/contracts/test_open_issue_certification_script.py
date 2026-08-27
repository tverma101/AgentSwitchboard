"""Static safety contract for the consolidated certification command."""

from pathlib import Path


def test_certification_script_does_not_shell_interpolate_or_capture_payloads() -> None:
    source = Path("scripts/certify_open_issues.py").read_text("utf-8")

    assert "shell=True" not in source
    assert "capture_output=True" not in source
    assert "stdout=subprocess.PIPE" not in source
    assert "stderr=subprocess.PIPE" not in source
    assert '"status": "unverified"' in source
    assert "subprocess.run(" in source
