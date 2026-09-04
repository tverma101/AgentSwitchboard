from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_ci_workflow_uses_hosted_runner_for_normal_ci() -> None:
    workflow = (_repo_root() / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("runs-on: ubuntu-latest") == 4
    assert "workflow_dispatch:" in workflow
    assert "runner_label" not in workflow
    assert "vars.HARNESS_RUNNER" not in workflow
    assert "harness-local" not in workflow
    assert "self-hosted" not in workflow
    assert "enable-cache: true" in workflow
    assert "cache-python: false" in workflow
    assert workflow.count("uv run --no-sync") == 4
    assert workflow.count("uv sync --locked") == 2
    assert "Prepare project environment" in workflow
    assert "Reuse warm Harness environment" not in workflow
    assert "PYTEST_XDIST_AUTO_NUM_WORKERS=6" not in workflow


def test_protected_pytest_transitively_requires_rust_tui() -> None:
    workflow = (_repo_root() / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    pytest_job = workflow.split("\n  pytest:\n", maxsplit=1)[1]
    assert "    name: pytest\n" in pytest_job
    assert "    needs: rust-tui\n" in pytest_job
    assert "uv run --no-sync pytest -q --tb=short" in pytest_job


def test_ci_processes_are_labeled_for_local_observability() -> None:
    conftest = (_repo_root() / "tests" / "conftest.py").read_text(encoding="utf-8")
    identity = (
        _repo_root() / "src" / "free_claude_code" / "core" / "process_identity.py"
    ).read_text(encoding="utf-8")

    assert 'set_process_identity("CI pytest"' in conftest
    assert "setproctitle.setproctitle(title)" in identity
    assert '"setproctitle>=1.3.7"' in (_repo_root() / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_issue_validator_remains_on_hosted_runner() -> None:
    workflow = (
        _repo_root() / ".github" / "workflows" / "validate-bug-report-version.yml"
    ).read_text(encoding="utf-8")

    assert "runs-on: ubuntu-latest" in workflow
