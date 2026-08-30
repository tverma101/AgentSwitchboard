from pathlib import Path

import pytest

from free_claude_code.cli import control_tui
from free_claude_code.cli.repo_picker import RepoEntry


_CWD_SENSITIVE_REPO_TESTS = frozenset(
    {
        "test_repositories_page_uses_live_local_inventory",
        "test_repositories_page_uses_fresh_cache_without_scanning",
    }
)


@pytest.fixture(autouse=True)
def deterministic_control_tui_repo_context(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep mocked repository-inventory tests independent of the runner checkout.

    ``ControlCenterApp`` intentionally defaults to the repository containing the
    process CWD. These two tests replace the inventory with one fixed Harness
    checkout, so letting GitHub Actions' own checkout become the selected repo
    makes the mock internally inconsistent. Pin only those cases to the same
    repository identity their mocked inventory supplies.
    """

    if request.node.name not in _CWD_SENSITIVE_REPO_TESTS:
        return

    expected = RepoEntry(
        "Harness",
        "/Users/tejas/Documents/ChatGPT/Harness",
        "main",
        "tverma101/AgentSwitchBoard",
    )

    def repository_from_path(
        path: Path,
        *,
        github_user: str | None = None,
        last_used: float = 0.0,
    ) -> RepoEntry:
        del path, github_user
        return RepoEntry(
            expected.name,
            expected.path,
            expected.branch,
            expected.remote,
            last_used,
        )

    monkeypatch.setattr(control_tui, "repository_from_path", repository_from_path)
