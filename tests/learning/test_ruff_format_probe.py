import subprocess
from pathlib import Path


def test_show_session_evidence_ruff_format_diff() -> None:
    target = Path(__file__).with_name("test_session_evidence.py")
    result = subprocess.run(
        ["ruff", "format", "--diff", str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout, result.stdout
