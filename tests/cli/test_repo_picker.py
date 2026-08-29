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
    github_authenticated_user,
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
    "failure",
    [OSError("git is unavailable"), subprocess.TimeoutExpired(["git"], 2)],
)
def test_git_probe_failures_are_treated_as_missing_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: Exception
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(repo_picker.subprocess, "run", fail_run)

    assert repo_picker._run_git(tmp_path, "status") == ""


def test_github_authenticated_user_returns_active_cli_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(command))
        return SimpleNamespace(returncode=0, stdout="tverma101\n")

    monkeypatch.setattr(repo_picker.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(repo_picker.subprocess, "run", fake_run)

    assert github_authenticated_user() == "tverma101"
    assert calls == [
        (
            "/usr/bin/gh",
            "api",
            "user",
            "--hostname",
            "github.com",
            "--jq",
            ".login",
        )
    ]


def test_github_authenticated_user_fails_closed_without_gh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo_picker.shutil, "which", lambda _name: None)

    assert github_authenticated_user() is None


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
    foreign_repo = tmp_path / "foreign"
    _init_repo(github_repo, ("origin", "https://github.com/acme/space.git"))
    _init_repo(
        unicode_repo,
        ("origin", "https://gitlab.com/acme/nope.git"),
        ("github", "git@github.com:acme/unicode.git"),
    )
    _init_repo(foreign_repo, ("origin", "https://github.com/other/foreign.git"))

    repos = discover_repos((tmp_path,), github_user="acme")

    assert {repo.name for repo in repos} == {"Repo With Spaces", "répo"}
    assert {repo.remote for repo in repos} == {"acme/space", "acme/unicode"}


def test_cache_round_trip_drops_deleted_paths(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    _init_repo(existing, ("origin", "https://github.com/acme/existing.git"))
    deleted = tmp_path / "deleted"
    cache = tmp_path / "repos.json"
    existing_entry = RepoEntry(
        existing.name,
        str(existing.resolve()),
        repo_picker._branch(existing),
        "acme/existing",
        4.0,
    )
    repos = [
        existing_entry,
        RepoEntry("deleted", str(deleted), "main", "acme/deleted", 8.0),
    ]

    save_cached_repos(repos, cache)

    assert load_cached_repos(cache, github_user="acme") == [existing_entry]


def test_cache_rebuilds_stale_display_metadata_from_git(tmp_path: Path) -> None:
    repository = tmp_path / "actual-name"
    _init_repo(repository, ("origin", "git@github.com:acme/actual.git"))
    cache = tmp_path / "repos.json"
    save_cached_repos(
        [
            RepoEntry(
                "fabricated-name",
                str(repository),
                "fabricated-branch",
                "evil/not-the-remote",
                3.0,
            )
        ],
        cache,
    )

    loaded = load_cached_repos(cache, github_user="acme")

    assert loaded == [
        RepoEntry(
            "actual-name",
            str(repository.resolve()),
            repo_picker._branch(repository),
            "acme/actual",
            3.0,
        )
    ]


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


def test_explicit_root_bypasses_unrelated_cache_without_overwriting_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cached_path = tmp_path / "cached"
    _init_repo(cached_path, ("origin", "https://github.com/acme/cached.git"))
    explicit_root = tmp_path / "explicit-root"
    explicit_root.mkdir()
    wanted_path = explicit_root / "wanted"
    wanted_path.mkdir()
    cache = tmp_path / "repos.json"

    cached = RepoEntry(
        cached_path.name,
        str(cached_path.resolve()),
        repo_picker._branch(cached_path),
        "acme/cached",
        9.0,
    )
    wanted = RepoEntry("wanted", str(wanted_path), "main", "acme/wanted")
    save_cached_repos([cached], cache)

    scanned: list[tuple[Path, ...]] = []
    launched: list[RepoEntry] = []

    def fake_discover(roots: tuple[Path, ...], *, github_user: str) -> list[RepoEntry]:
        scanned.append(roots)
        assert github_user == "acme"
        return [wanted]

    def fake_launch(repo: RepoEntry) -> None:
        launched.append(repo)
        raise RuntimeError("launch intercepted")

    monkeypatch.setattr(repo_picker, "cache_path", lambda: cache)
    monkeypatch.setattr(repo_picker, "github_authenticated_user", lambda: "acme")
    monkeypatch.setattr(repo_picker, "discover_repos", fake_discover)
    monkeypatch.setattr(repo_picker, "choose_repo", lambda repos, _query: repos[0])
    monkeypatch.setattr(repo_picker, "launch_repo", fake_launch)

    with pytest.raises(RuntimeError, match="launch intercepted"):
        repo_picker.main(["--root", str(explicit_root)])

    assert scanned == [(explicit_root,)]
    assert launched == [wanted]
    assert load_cached_repos(cache, github_user="acme") == [cached]
