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
    assert workflow.count("uv run --no-sync") == 4
    assert workflow.count("uv sync --locked") == 1
    assert (
        'environment_path="$environment_root/${RUNNER_OS}-${RUNNER_ARCH}-py314"'
        in workflow
    )
    assert 'UV_PROJECT_ENVIRONMENT="$environment_path"' in workflow


def test_issue_validator_remains_on_hosted_runner() -> None:
    workflow = (
        _repo_root() / ".github" / "workflows" / "validate-bug-report-version.yml"
    ).read_text(encoding="utf-8")

    assert "runs-on: ubuntu-latest" in workflow
