"""Temporary CI formatter probe; delete after capturing Ruff's exact diff."""

import subprocess


def test_ruff_formatter_diff() -> None:
    result = subprocess.run(
        [
            "ruff",
            "format",
            "--diff",
            "src/free_claude_code/learning/hooks.py",
            "tests/learning/test_auto_reviewer_install.py",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
