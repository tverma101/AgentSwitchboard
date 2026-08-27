"""Contracts for bounded certification-runner execution."""

import subprocess
from pathlib import Path

import pytest

import scripts.certify_open_issues as runner
from smoke.lib.open_issue_certification import CertificationStep


def test_runner_marks_a_timed_out_step_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    step = CertificationStep(
        step_id="timeout",
        issues=(1,),
        evidence="deterministic",
        argv=("python", "-c", "pass"),
        timeout_seconds=0.1,
    )

    def raise_timeout(
        *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["python"], 0.1)

    monkeypatch.setattr(runner.subprocess, "run", raise_timeout)

    result = runner._run_step(step, root=tmp_path)

    assert result["status"] == "failed"
    assert result["reason"] == "timeout"
    assert result["returncode"] is None
    assert result["timeout_seconds"] == 0.1
