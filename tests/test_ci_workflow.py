from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_ci_workflow_routes_trusted_jobs_to_the_configured_runner() -> None:
    workflow = (_repo_root() / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    expected_runs_on = (
        "runs-on: ${{ github.event_name == 'pull_request' "
        "&& github.event.pull_request.head.repo.full_name != github.repository "
        "&& 'ubuntu-latest' || vars.HARNESS_RUNNER || 'ubuntu-latest' }}"
    )

    assert workflow.count(expected_runs_on) == 2
    assert (
        "Never execute fork-controlled code on the persistent self-hosted runner."
        in workflow
    )
    assert "enable-cache: false" in workflow
    assert "cache-python: false" in workflow
    assert workflow.count("uv run --no-sync") == 4
    assert "uv sync --locked" in workflow
    assert "PYTEST_XDIST_AUTO_NUM_WORKERS=6" in workflow
    assert "hw.perflevel0.physicalcpu" in workflow


def test_issue_validator_remains_on_hosted_runner() -> None:
    workflow = (
        _repo_root() / ".github" / "workflows" / "validate-bug-report-version.yml"
    ).read_text(encoding="utf-8")

    assert "runs-on: ubuntu-latest" in workflow
