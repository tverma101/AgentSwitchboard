"""GitHub-backed repository inventory and picker for launching ``fccdanger``."""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

from .selection import SelectionItem, choose_item
from .selection import fuzzy_match as match_items

_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
_GITHUB_IDENTITY_TIMEOUT_SECONDS = 5
_SKIP_DIRS = frozenset(
    {
        ".cache",
        ".git",
        ".idea",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "Library",
        "Trash",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "vendor",
    }
)


def _canonical_repo_path(value: str | Path) -> str:
    """Return a stable checkout key without making a broken path fatal."""

    try:
        return str(Path(value).expanduser().resolve())
    except OSError, RuntimeError:
        return str(value)


@dataclass(frozen=True, slots=True)
class RepoEntry:
    """One local GitHub checkout shown by the picker."""

    name: str
    path: str
    branch: str
    remote: str
    last_used: float = 0.0

    @property
    def display_path(self) -> str:
        """Return a compact home-relative path when possible."""

        try:
            path = Path(self.path).expanduser().resolve()
            home = Path.home().expanduser().resolve()
            relative = path.relative_to(home)
        except OSError, RuntimeError, ValueError:
            return self.path
        if not relative.parts:
            return "~"
        return f"~{os.sep}{relative}"

    @property
    def repository_name(self) -> str:
        """Return the repository name, independent of its checkout directory."""

        return self.remote.rsplit("/", 1)[-1] if self.remote else self.name

    @property
    def identity(self) -> str:
        """Return the clearest stable repository identity available."""

        return self.remote or self.repository_name

    @property
    def selection_detail(self) -> str:
        """Return labeled checkout metadata for the shared terminal picker."""

        checkout = (
            f"checkout {self.name}"
            if self.name.casefold() != self.repository_name.casefold()
            else ""
        )
        return " · ".join(
            value
            for value in (checkout, f"branch {self.branch}", self.display_path)
            if value
        )


def default_roots() -> tuple[Path, ...]:
    """Return existing roots, prioritizing the current working directory."""

    home = Path.home()
    try:
        current = Path.cwd()
    except OSError:
        current = None
    candidates = (current, home / "src", home / "Projects", home / "Documents")
    roots: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path is None:
            continue
        try:
            resolved = path.expanduser().resolve(strict=True)
        except OSError, RuntimeError:
            continue
        if resolved.is_dir() and resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return tuple(roots)


def cache_path() -> Path:
    """Return the repo discovery cache path."""

    configured = os.environ.get("FCC_REPOS_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "free-claude-code" / "repos.json"


def _run_git(path: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except OSError, subprocess.TimeoutExpired:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def github_authenticated_user() -> str | None:
    """Return the active GitHub CLI account without exposing its token."""

    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        completed = subprocess.run(
            [gh, "api", "user", "--hostname", "github.com", "--jq", ".login"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_GITHUB_IDENTITY_TIMEOUT_SECONDS,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None
    login = completed.stdout.strip()
    if not login or any(character.isspace() for character in login):
        return None
    return login


def _remote_urls(path: Path) -> tuple[tuple[str, str], ...]:
    """Return configured remote names and URLs without exposing credentials."""

    output = _run_git(path, "config", "--get-regexp", r"^remote\..*\.url$")
    remotes: list[tuple[str, str]] = []
    for line in output.splitlines():
        key, _, url = line.partition(" ")
        prefix, _, name = key.partition(".")
        if prefix != "remote" or not name.endswith(".url"):
            continue
        remote_name = name.removesuffix(".url")
        url = url.strip()
        if remote_name and url:
            remotes.append((remote_name, url))
    return tuple(remotes)


def _github_remotes(path: Path) -> tuple[str, ...]:
    remotes: list[str] = []
    for _name, url in _remote_urls(path):
        if _is_github_remote(url):
            slug = _remote_slug(url)
            if slug and slug not in remotes:
                remotes.append(slug)
    return tuple(remotes)


def _remote_label(url: str) -> str:
    """Return a compact remote identity with credentials and query data removed."""

    value = url.strip().removesuffix(".git").rstrip("/")
    if _is_github_remote(value):
        return _remote_slug(value)

    if "://" not in value and ":" in value:
        host, path = value.split(":", 1)
        host = host.rsplit("@", 1)[-1]
        path = path.strip("/")
        return f"{host}/{path}" if host and path else host or path

    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
    except ValueError:
        sanitized = value.rsplit("@", 1)[-1]
        return sanitized
    path = parsed.path.strip("/")
    if host and path:
        return f"{host}/{path}"
    return path or host


def _repository_remote(path: Path, *, github_user: str | None = None) -> str:
    """Return a configured GitHub remote, optionally scoped to an owner."""

    return _github_remote(path, github_user=github_user)


def _github_remote(path: Path, *, github_user: str | None = None) -> str:
    """Return a GitHub remote, preferring one owned by ``github_user``."""

    remotes = _github_remotes(path)
    if github_user is None:
        return remotes[0] if remotes else ""
    owner = github_user.casefold()
    return next(
        (remote for remote in remotes if _remote_owner(remote).casefold() == owner),
        "",
    )


def _is_github_remote(url: str) -> bool:
    lowered = url.casefold()
    return (
        lowered.startswith("git@github.com:")
        or lowered.startswith("ssh://git@github.com/")
        or lowered.startswith("https://github.com/")
        or lowered.startswith("http://github.com/")
    )


def _remote_slug(url: str) -> str:
    value = url.strip().removesuffix(".git").rstrip("/")
    if value.casefold().startswith("git@github.com:"):
        return value.split(":", 1)[1]
    marker = "github.com/"
    index = value.casefold().find(marker)
    return value[index + len(marker) :] if index >= 0 else value


def _remote_owner(remote: str) -> str:
    """Return the owner portion of an ``owner/repository`` slug."""

    return remote.split("/", 1)[0] if "/" in remote else ""


def _branch(path: Path) -> str:
    branch = _run_git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch:
        return branch
    detached = _run_git(path, "rev-parse", "--short", "HEAD")
    return f"detached:{detached}" if detached else "?"


def _git_root(path: Path) -> Path | None:
    """Return the canonical Git root for a path or one of its parents."""

    try:
        candidate = path.expanduser().resolve(strict=True)
    except OSError, RuntimeError:
        return None
    output = _run_git(candidate, "rev-parse", "--show-toplevel")
    if not output:
        return None
    try:
        root = Path(output).resolve(strict=True)
    except OSError, RuntimeError:
        return None
    return root if root.is_dir() else None


def _is_repo_root(path: Path) -> bool:
    root = _git_root(path)
    try:
        return root == path.expanduser().resolve(strict=True)
    except OSError, RuntimeError:
        return False


def _has_git_metadata(path: Path) -> bool:
    """Return whether a directory has the marker used by a Git checkout."""

    marker = path / ".git"
    return marker.is_dir() or marker.is_file()


def _is_linked_worktree(path: Path) -> bool:
    """Return whether ``path`` is a linked Git worktree checkout.

    A linked worktree has a ``.git`` file pointing into the primary
    repository's ``.git/worktrees`` directory.  It is a real checkout for Git
    operations, but it is not an independent project folder and must not
    appear as a second repository in the picker.
    """

    marker = path / ".git"
    if not marker.is_file():
        return False
    try:
        line = marker.read_text(encoding="utf-8").splitlines()[0].strip()
    except OSError, IndexError, UnicodeError:
        return False
    prefix, separator, raw_gitdir = line.partition(":")
    if prefix.casefold() != "gitdir" or not separator or not raw_gitdir.strip():
        return False
    gitdir = Path(raw_gitdir.strip())
    if not gitdir.is_absolute():
        gitdir = marker.parent / gitdir
    try:
        return gitdir.resolve().parent.name.casefold() == "worktrees"
    except OSError, RuntimeError:
        return False


def repository_from_path(
    path: Path,
    *,
    github_user: str | None = None,
    last_used: float = 0.0,
) -> RepoEntry | None:
    """Build live repository metadata from a root or a path inside a checkout."""

    root = _git_root(path)
    if root is None:
        return None
    if _is_linked_worktree(root):
        return None
    remote = _repository_remote(root, github_user=github_user)
    if not remote:
        return None
    return RepoEntry(
        name=root.name,
        path=str(root),
        branch=_branch(root),
        remote=remote,
        last_used=last_used,
    )


def deduplicate_repos(repos: Iterable[RepoEntry]) -> list[RepoEntry]:
    """Return one canonical entry per checkout, preserving distinct clones."""

    unique: dict[str, RepoEntry] = {}
    for repo in repos:
        path = _canonical_repo_path(repo.path)
        candidate = repo if repo.path == path else replace(repo, path=path)
        existing = unique.get(path)
        if existing is None:
            unique[path] = candidate
            continue
        # Multiple scan roots can observe one checkout with partially
        # populated metadata. Merge those observations instead of allowing a
        # weaker first record to win.
        unique[path] = RepoEntry(
            name=existing.name or candidate.name,
            path=path,
            branch=(
                candidate.branch
                if candidate.branch and candidate.branch != "?"
                else existing.branch
            ),
            remote=existing.remote or candidate.remote,
            last_used=max(existing.last_used, candidate.last_used),
        )
    return sorted(
        unique.values(),
        key=lambda repo: (
            repo.identity.casefold(),
            repo.repository_name.casefold(),
            repo.display_path.casefold(),
        ),
    )


def _normalized_scan_roots(roots: Iterable[Path]) -> tuple[Path, ...]:
    """Resolve roots and remove nested paths before walking the filesystem."""

    normalized: list[Path] = []
    for root in roots:
        try:
            candidate = root.expanduser().resolve(strict=True)
        except OSError, RuntimeError:
            continue
        if not candidate.is_dir():
            continue
        if any(
            candidate == parent or candidate.is_relative_to(parent)
            for parent in normalized
        ):
            continue
        normalized = [
            parent for parent in normalized if not parent.is_relative_to(candidate)
        ]
        normalized.append(candidate)
    return tuple(normalized)


def discover_repos(
    roots: tuple[Path, ...], *, github_user: str | None = None
) -> list[RepoEntry]:
    """Discover real GitHub checkouts, optionally scoped to an account.

    Local-only and non-GitHub repositories are intentionally excluded even
    when GitHub CLI authentication is unavailable.  That keeps the picker
    aligned with the repositories it can identify and avoids presenting
    linked worktrees as separate projects.
    """

    discovered: dict[str, RepoEntry] = {}
    for root in _normalized_scan_roots(roots):
        containing_repo = repository_from_path(root, github_user=github_user)
        if containing_repo is not None:
            discovered[containing_repo.path] = containing_repo
            # A root inside a checkout is already fully represented. Do not
            # walk every child just to rediscover the same repository.
            continue
        for current, directories, _files in os.walk(root, topdown=True):
            directories[:] = [
                name
                for name in directories
                if name not in _SKIP_DIRS and not name.startswith(".")
            ]
            candidate = Path(current)
            # Most walked directories are ordinary folders. Checking for the
            # marker first avoids a Git subprocess for every one of them.
            if not _has_git_metadata(candidate):
                continue

            repo = repository_from_path(candidate, github_user=github_user)
            if repo is not None:
                discovered[repo.path] = repo
            directories.clear()

    return deduplicate_repos(discovered.values())


def load_cached_repos(
    path: Path | None = None, *, github_user: str | None = None
) -> list[RepoEntry]:
    """Load cached paths, rebuilding every display field from live Git state.

    The cache is only a list of recently discovered paths. Names, branches, and
    remotes are never trusted from JSON because a stale cache must not make a
    missing path or an unrelated checkout look like a real repository.
    """

    path = cache_path() if path is None else path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError, TypeError:
        return []
    if not isinstance(payload, dict):
        return []
    cached_user = payload.get("github_user")
    if (
        github_user is not None
        and isinstance(cached_user, str)
        and cached_user.casefold() != github_user.casefold()
    ):
        # A shared cache may have been written by a different local GitHub
        # account. Force discovery rather than showing another user's clones.
        return []

    entries: list[RepoEntry] = []
    for raw in payload.get("repos", []):
        if not isinstance(raw, dict):
            continue
        try:
            candidate = Path(str(raw["path"])).expanduser().resolve(strict=True)
            last_used = float(raw.get("last_used", 0.0))
        except KeyError, TypeError, ValueError:
            continue
        except OSError, RuntimeError:
            continue
        if not math.isfinite(last_used) or last_used < 0:
            last_used = 0.0
        repo = repository_from_path(
            candidate,
            github_user=github_user,
            last_used=last_used,
        )
        if repo is not None:
            entries.append(repo)
    return deduplicate_repos(entries)


def save_cached_repos(
    repos: Iterable[RepoEntry],
    path: Path | None = None,
    *,
    github_user: str | None = None,
) -> None:
    """Persist the bounded, de-duplicated discovery cache."""

    path = cache_path() if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": time.time(),
        "github_user": github_user,
        "repos": [asdict(repo) for repo in deduplicate_repos(repos)],
    }
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        # A failed write must not leave a stale temporary file that can be
        # mistaken for the authoritative cache by tooling or cleanup jobs.
        with suppress(OSError):
            temporary.unlink()


def cache_is_fresh(path: Path | None = None) -> bool:
    """Return whether the cache is young enough to avoid a synchronous scan."""

    path = cache_path() if path is None else path
    try:
        age = time.time() - path.stat().st_mtime
        return 0 <= age < _CACHE_MAX_AGE_SECONDS
    except OSError:
        return False


def fuzzy_match(repos: list[RepoEntry], query: str) -> list[RepoEntry]:
    """Return repositories ranked by the shared terminal picker matcher."""

    repos = deduplicate_repos(repos)
    matches = match_items(
        [
            SelectionItem(
                item_id=repo.path,
                label=repo.identity,
                detail=repo.selection_detail,
                last_used=repo.last_used,
            )
            for repo in repos
        ],
        query,
    )
    by_path = {repo.path: repo for repo in repos}
    return [by_path[item.item_id] for item in matches]


def choose_repo(
    repos: list[RepoEntry],
    initial_query: str = "",
    *,
    selected_path: str | None = None,
) -> RepoEntry | None:
    """Open the shared picker and return the selected repository."""

    repos = deduplicate_repos(repos)
    selected = choose_item(
        [
            SelectionItem(
                item_id=repo.path,
                label=repo.identity,
                detail=repo.selection_detail,
                last_used=repo.last_used,
            )
            for repo in repos
        ],
        title="AgentSwitchboard repositories",
        initial_query=initial_query,
        default_item_id=selected_path,
        footer="type filter · ↑↓ move · enter launch · esc cancel · * default",
    )
    if selected is None:
        return None
    return next((repo for repo in repos if repo.path == selected.item_id), None)


def mark_repo_used(repos: Iterable[RepoEntry], selected: RepoEntry) -> list[RepoEntry]:
    """Update one checkout's recency while preserving inventory metadata."""

    now = time.time()
    selected_path = _canonical_repo_path(selected.path)
    normalized_repos = deduplicate_repos(repos)
    return [
        RepoEntry(
            name=repo.name,
            path=_canonical_repo_path(repo.path),
            branch=repo.branch,
            remote=repo.remote,
            last_used=(
                now
                if _canonical_repo_path(repo.path) == selected_path
                else repo.last_used
            ),
        )
        for repo in normalized_repos
    ]


def launch_repo(repo: RepoEntry) -> NoReturn:
    """Replace the picker with canonical ``fccdanger`` in the selected cwd."""

    previous = Path.cwd()
    os.chdir(repo.path)
    try:
        os.execvp("fccdanger", ["fccdanger"])
    finally:
        # ``execvp`` normally never returns, but restoring the parent process
        # cwd keeps tests, embedders, and a mocked launcher safe.
        os.chdir(previous)
    raise AssertionError("os.execvp returned unexpectedly")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pick a local GitHub checkout and launch fccdanger"
    )
    parser.add_argument("query", nargs="?", default="", help="initial fuzzy filter")
    parser.add_argument(
        "--refresh", action="store_true", help="force repository rescan"
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        metavar="PATH",
        help="scan root; may be repeated",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for ``fcc-repos``."""

    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    explicit_roots = bool(args.root)
    roots = tuple(Path(value).expanduser() for value in args.root) or default_roots()
    cache = cache_path()
    try:
        github_user = github_authenticated_user()
    except Exception:
        github_user = None
    try:
        current = repository_from_path(Path.cwd(), github_user=github_user)
    except Exception:
        current = None

    if explicit_roots:
        repos = discover_repos(roots, github_user=github_user)
    else:
        repos = (
            [] if args.refresh else load_cached_repos(cache, github_user=github_user)
        )
        if args.refresh or not repos or not cache_is_fresh(cache):
            previous_last_used = {
                _canonical_repo_path(repo.path): repo.last_used for repo in repos
            }
            repos = [
                replace(
                    repo,
                    last_used=previous_last_used.get(
                        _canonical_repo_path(repo.path), 0.0
                    ),
                )
                for repo in discover_repos(roots, github_user=github_user)
            ]
            try:
                save_cached_repos(repos, cache, github_user=github_user)
            except OSError as exc:
                print(
                    f"Repository cache unavailable: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
        if current is not None and current.path not in {repo.path for repo in repos}:
            repos.append(current)
            repos = deduplicate_repos(repos)

    if not repos:
        print("No local GitHub checkouts found.", file=sys.stderr)
        print("Try: fcc-repos --refresh --root ~/src", file=sys.stderr)
        raise SystemExit(1)

    selected_path = (
        current.path
        if current is not None and any(repo.path == current.path for repo in repos)
        else None
    )
    selected = (
        choose_repo(repos, args.query, selected_path=selected_path)
        if selected_path is not None
        else choose_repo(repos, args.query)
    )
    if selected is None:
        return
    if not explicit_roots:
        try:
            save_cached_repos(
                mark_repo_used(repos, selected), cache, github_user=github_user
            )
        except OSError as exc:
            print(
                f"Repository cache unavailable: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
    launch_repo(selected)
