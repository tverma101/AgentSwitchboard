"""Dependency-neutral local GitHub checkout inventory.

The Admin API and terminal clients share this metadata boundary.  It never
trusts cached display fields: every cached path is revalidated against live Git
metadata before it can be returned to a user.
"""

import json
import math
import os
import shutil
import subprocess
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path

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
    """One local GitHub checkout shown by a client surface."""

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
        """Return labeled checkout metadata for a picker or inspector."""

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


def _github_remotes(path: Path) -> tuple[str, ...]:
    remotes: list[str] = []
    for _name, url in _remote_urls(path):
        if _is_github_remote(url):
            slug = _remote_slug(url)
            if slug and slug not in remotes:
                remotes.append(slug)
    return tuple(remotes)


def _remote_owner(remote: str) -> str:
    """Return the owner portion of an ``owner/repository`` slug."""

    return remote.split("/", 1)[0] if "/" in remote else ""


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


def _is_linked_worktree(path: Path) -> bool:
    """Return whether ``path`` is a linked Git worktree checkout."""

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
    if root is None or _is_linked_worktree(root):
        return None
    remote = _github_remote(root, github_user=github_user)
    if not remote:
        return None
    return RepoEntry(
        name=root.name,
        path=str(root),
        branch=_branch(root),
        remote=remote,
        last_used=last_used,
    )


def deduplicate_repos(
    repos: list[RepoEntry] | tuple[RepoEntry, ...],
) -> list[RepoEntry]:
    """Return one canonical entry per checkout, preserving distinct clones."""

    unique: dict[str, RepoEntry] = {}
    for repo in repos:
        path = _canonical_repo_path(repo.path)
        candidate = repo if repo.path == path else replace(repo, path=path)
        existing = unique.get(path)
        if existing is None:
            unique[path] = candidate
            continue
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


def _normalized_scan_roots(roots: tuple[Path, ...]) -> tuple[Path, ...]:
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
    """Discover real GitHub checkouts and exclude linked worktrees."""

    discovered: dict[str, RepoEntry] = {}
    for root in _normalized_scan_roots(roots):
        containing_repo = repository_from_path(root, github_user=github_user)
        if containing_repo is not None:
            discovered[containing_repo.path] = containing_repo
            continue
        for current, directories, _files in os.walk(root, topdown=True):
            directories[:] = [
                name
                for name in directories
                if name not in _SKIP_DIRS and not name.startswith(".")
            ]
            candidate = Path(current)
            if not (candidate / ".git").is_dir() and not (candidate / ".git").is_file():
                continue
            repo = repository_from_path(candidate, github_user=github_user)
            if repo is not None:
                discovered[repo.path] = repo
            directories.clear()
    return deduplicate_repos(list(discovered.values()))


def cache_path() -> Path:
    """Return the repository discovery cache path."""

    configured = os.environ.get("FCC_REPOS_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "free-claude-code" / "repos.json"


def load_cached_repos(
    path: Path | None = None, *, github_user: str | None = None
) -> list[RepoEntry]:
    """Load cached paths while rebuilding every display field from live Git."""

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
        return []

    entries: list[RepoEntry] = []
    for raw in payload.get("repos", []):
        if not isinstance(raw, dict):
            continue
        try:
            candidate = Path(str(raw["path"])).expanduser().resolve(strict=True)
            last_used = float(raw.get("last_used", 0.0))
        except KeyError, TypeError, ValueError, OSError, RuntimeError:
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
    repos: list[RepoEntry] | tuple[RepoEntry, ...],
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


def mark_repo_used(
    repos: list[RepoEntry] | tuple[RepoEntry, ...], selected: RepoEntry
) -> list[RepoEntry]:
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


def load_repository_inventory(
    *, refresh: bool = False
) -> tuple[list[RepoEntry], str | None]:
    """Load the safe local GitHub checkout inventory and suggested selection."""

    github_user = github_authenticated_user()
    cache = cache_path()
    repos: list[RepoEntry] = []
    if not refresh and cache_is_fresh(cache):
        repos = load_cached_repos(cache, github_user=github_user)
    if not repos:
        repos = discover_repos(default_roots(), github_user=github_user)
        with suppress(OSError):
            save_cached_repos(repos, cache, github_user=github_user)

    try:
        current = repository_from_path(Path.cwd(), github_user=github_user)
    except OSError, RuntimeError:
        current = None
    if current is not None and current.path not in {repo.path for repo in repos}:
        repos.append(current)
    repos = deduplicate_repos(repos)

    selected_path: str | None = None
    if current is not None and any(repo.path == current.path for repo in repos):
        selected_path = current.path
    else:
        recently_used = [repo for repo in repos if repo.last_used > 0]
        if recently_used:
            selected_path = max(recently_used, key=lambda repo: repo.last_used).path
    return repos, selected_path


def select_repository(path: str) -> tuple[RepoEntry, bool]:
    """Validate, mark, and cache one local GitHub checkout selection."""

    github_user = github_authenticated_user()
    repo = repository_from_path(Path(path).expanduser(), github_user=github_user)
    if repo is None:
        raise ValueError(
            "That path is not inside a readable local GitHub repository "
            "or is a linked worktree."
        )
    try:
        repos, _selected_path = load_repository_inventory()
    except OSError, RuntimeError:
        repos = []
    marked = mark_repo_used([*repos, repo], repo)
    selected = next(
        (candidate for candidate in marked if candidate.path == repo.path),
        repo,
    )
    try:
        save_cached_repos(marked, cache_path(), github_user=github_user)
    except OSError:
        return selected, False
    return selected, True
