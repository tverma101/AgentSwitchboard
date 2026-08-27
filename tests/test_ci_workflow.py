from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_ci_workflow_routes_only_trusted_pull_requests_to_self_hosted_runner() -> None:
    workflow = (_repo_root() / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    expected_runs_on = (
        "runs-on: ${{ github.event_name == 'workflow_dispatch' "
        "&& inputs.runner_label || github.event_name == 'pull_request' "
        "&& github.event.pull_request.head.repo.full_name != github.repository "
        "&& 'ubuntu-latest' || vars.HARNESS_RUNNER || 'ubuntu-latest' }}"
    )

    assert workflow.count(expected_runs_on) == 2
    assert "workflow_dispatch:" in workflow
    assert "default: ubuntu-latest" in workflow
    assert "- harness-burst" in workflow
    assert workflow.count("vars.HARNESS_RUNNER") == 2
    assert (
        "Never execute fork-controlled code on the persistent self-hosted runner."
        in workflow
    )
    assert "enable-cache: false" in workflow
    assert "cache-python: false" in workflow
    assert workflow.count("uv run --no-sync") == 4
    assert workflow.count("uv sync --locked") == 1
    assert (
        'environment_path="$environment_root/${RUNNER_OS}-${RUNNER_ARCH}-py314"'
        in workflow
    )
    assert 'UV_PROJECT_ENVIRONMENT="$environment_path"' in workflow
    assert "PYTEST_XDIST_AUTO_NUM_WORKERS=6" in workflow
    assert "hw.perflevel0.physicalcpu" in workflow


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
