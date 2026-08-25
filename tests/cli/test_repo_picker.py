import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import free_claude_code.cli.repo_picker as repo_picker
from free_claude_code.cli.repo_picker import (
    RepoEntry,
    _is_github_remote,
    _remote_slug,
    choose_repo,
    discover_repos,
    fuzzy_match,
    launch_repo,
    load_cached_repos,
    save_cached_repos,
)


def _init_repo(path: Path, *remotes: tuple[str, str]) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for name, url in remotes:
        subprocess.run(
            ["git", "-C", str(path), "remote", "add", name, url],
            check=True,
        )


def test_github_remote_recognizes_https_ssh_and_scp_forms() -> None:
    assert _is_github_remote("https://github.com/acme/repo.git")
    assert _is_github_remote("ssh://git@github.com/acme/repo.git")
    assert _is_github_remote("git@github.com:acme/repo.git")
    assert not _is_github_remote("https://gitlab.com/acme/repo.git")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/acme/repo.git", "acme/repo"),
        ("ssh://git@github.com/acme/repo.git", "acme/repo"),
        ("git@github.com:acme/repo.git", "acme/repo"),
    ],
)
def test_remote_slug_is_compact(url: str, expected: str) -> None:
    assert _remote_slug(url) == expected


def test_discovery_keeps_only_github_repos_and_handles_multiple_remotes(
    tmp_path: Path,
) -> None:
    github_repo = tmp_path / "Repo With Spaces"
    unicode_repo = tmp_path / "répo"
    other_repo = tmp_path / "gitlab"
    _init_repo(github_repo, ("origin", "https://github.com/acme/space.git"))
    _init_repo(
        unicode_repo,
        ("origin", "https://gitlab.com/acme/nope.git"),
        ("github", "git@github.com:acme/unicode.git"),
    )
    _init_repo(other_repo, ("origin", "https://gitlab.com/acme/nope.git"))

    repos = discover_repos((tmp_path,))

    assert {repo.name for repo in repos} == {"Repo With Spaces", "répo"}
    assert {repo.remote for repo in repos} == {"acme/space", "acme/unicode"}


def test_cache_round_trip_drops_deleted_paths(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    deleted = tmp_path / "deleted"
    cache = tmp_path / "repos.json"
    repos = [
        RepoEntry("existing", str(existing), "main", "acme/existing", 4.0),
        RepoEntry("deleted", str(deleted), "main", "acme/deleted", 8.0),
    ]

    save_cached_repos(repos, cache)

    assert load_cached_repos(cache) == [repos[0]]


def test_fuzzy_match_prefers_tighter_match_and_recent_when_empty(
    tmp_path: Path,
) -> None:
    repos = [
        RepoEntry("Harness", str(tmp_path / "Harness"), "main", "acme/Harness", 1.0),
        RepoEntry(
            "HugeHarnessThing", str(tmp_path / "other"), "main", "acme/other", 2.0
        ),
    ]

    assert fuzzy_match(repos, "harn")[0].name == "Harness"
    assert fuzzy_match(repos, "")[0].name == "HugeHarnessThing"


def test_non_tty_filter_with_no_match_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repos = [RepoEntry("Harness", str(tmp_path), "main", "acme/Harness")]
    non_tty = SimpleNamespace(isatty=lambda: False)
    monkeypatch.setattr(repo_picker.sys, "stdin", non_tty)
    monkeypatch.setattr(repo_picker.sys, "stdout", non_tty)

    assert choose_repo(repos, "definitely-no-match") is None


def test_launch_repo_execs_canonical_fccdanger_with_selected_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_path = tmp_path / "repo with spaces"
    repo_path.mkdir()
    repo = RepoEntry("repo", str(repo_path), "main", "acme/repo")
    calls: list[tuple[str, list[str], str]] = []

    def fake_execvp(file: str, argv: list[str]) -> None:
        calls.append((file, argv, os.getcwd()))
        raise RuntimeError("exec intercepted")

    monkeypatch.setattr(os, "execvp", fake_execvp)
    previous = Path.cwd()
    try:
        with pytest.raises(RuntimeError, match="exec intercepted"):
            launch_repo(repo)
    finally:
        os.chdir(previous)

    assert calls == [("fccdanger", ["fccdanger"], str(repo_path))]
