"""Tiny terminal picker for launching ``fccdanger`` in a local GitHub repo."""

import argparse
import curses
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NoReturn

_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
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


@dataclass(frozen=True, slots=True)
class RepoEntry:
    """One local GitHub-backed repository shown by the picker."""

    name: str
    path: str
    branch: str
    remote: str
    last_used: float = 0.0

    @property
    def display_path(self) -> str:
        """Return a compact home-relative path when possible."""

        home = str(Path.home())
        if self.path == home:
            return "~"
        if self.path.startswith(f"{home}{os.sep}"):
            return f"~{self.path[len(home):]}"
        return self.path


def default_roots() -> tuple[Path, ...]:
    """Return existing default scan roots for a personal macOS/Linux setup."""

    home = Path.home()
    candidates = (home / "src", home / "Projects", home / "Documents")
    return tuple(path for path in candidates if path.is_dir())


def cache_path() -> Path:
    """Return the repo discovery cache path."""

    configured = os.environ.get("FCC_REPOS_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "free-claude-code" / "repos.json"


def _run_git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _github_remote(path: Path) -> str:
    output = _run_git(path, "config", "--get-regexp", r"^remote\..*\.url$")
    for line in output.splitlines():
        _, _, url = line.partition(" ")
        url = url.strip()
        if _is_github_remote(url):
            return _remote_slug(url)
    return ""


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


def _branch(path: Path) -> str:
    branch = _run_git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch:
        return branch
    detached = _run_git(path, "rev-parse", "--short", "HEAD")
    return f"detached:{detached}" if detached else "?"


def _is_repo_root(path: Path) -> bool:
    git_marker = path / ".git"
    if not git_marker.exists():
        return False
    return _run_git(path, "rev-parse", "--show-toplevel") == str(path.resolve())


def discover_repos(roots: tuple[Path, ...]) -> list[RepoEntry]:
    """Discover local GitHub-backed repositories beneath bounded roots."""

    discovered: dict[str, RepoEntry] = {}
    for root in roots:
        root = root.expanduser().resolve()
        if not root.is_dir():
            continue
        for current, directories, _files in os.walk(root, topdown=True):
            directories[:] = [
                name
                for name in directories
                if name not in _SKIP_DIRS and not name.startswith(".")
            ]
            candidate = Path(current)
            if not _is_repo_root(candidate):
                continue

            remote = _github_remote(candidate)
            if remote:
                resolved = str(candidate.resolve())
                discovered[resolved] = RepoEntry(
                    name=candidate.name,
                    path=resolved,
                    branch=_branch(candidate),
                    remote=remote,
                )
            directories.clear()

    return sorted(discovered.values(), key=lambda repo: repo.name.casefold())


def load_cached_repos(path: Path | None = None) -> list[RepoEntry]:
    """Load valid cached repository entries, ignoring corrupt/stale paths."""

    path = cache_path() if path is None else path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []

    entries: list[RepoEntry] = []
    for raw in payload.get("repos", []):
        if not isinstance(raw, dict):
            continue
        try:
            entry = RepoEntry(
                name=str(raw["name"]),
                path=str(raw["path"]),
                branch=str(raw.get("branch", "?")),
                remote=str(raw.get("remote", "")),
                last_used=float(raw.get("last_used", 0.0)),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if Path(entry.path).is_dir():
            entries.append(entry)
    return entries


def save_cached_repos(repos: list[RepoEntry], path: Path | None = None) -> None:
    """Persist the bounded discovery cache."""

    path = cache_path() if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": time.time(), "repos": [asdict(repo) for repo in repos]}
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def cache_is_fresh(path: Path | None = None) -> bool:
    """Return whether the cache is young enough to avoid a synchronous scan."""

    path = cache_path() if path is None else path
    try:
        return time.time() - path.stat().st_mtime < _CACHE_MAX_AGE_SECONDS
    except OSError:
        return False


def fuzzy_match(repos: list[RepoEntry], query: str) -> list[RepoEntry]:
    """Return repositories ranked by a cheap subsequence match."""

    query = query.casefold().strip()
    if not query:
        return sorted(repos, key=lambda repo: (-repo.last_used, repo.name.casefold()))

    scored: list[tuple[int, RepoEntry]] = []
    for repo in repos:
        haystack = f"{repo.name} {repo.remote} {repo.path}".casefold()
        score = _subsequence_score(haystack, query)
        if score is not None:
            scored.append((score, repo))
    scored.sort(key=lambda item: (item[0], -item[1].last_used, item[1].name.casefold()))
    return [repo for _, repo in scored]


def _subsequence_score(haystack: str, needle: str) -> int | None:
    position = -1
    score = 0
    for character in needle:
        next_position = haystack.find(character, position + 1)
        if next_position < 0:
            return None
        score += next_position - position - 1
        position = next_position
    return score


def choose_repo(repos: list[RepoEntry], initial_query: str = "") -> RepoEntry | None:
    """Open the tiny curses picker and return the selected repository."""

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return fuzzy_match(repos, initial_query)[0] if repos else None
    return curses.wrapper(_picker, repos, initial_query)


def _picker(screen: curses.window, repos: list[RepoEntry], initial_query: str) -> RepoEntry | None:
    curses.curs_set(0)
    screen.keypad(True)
    query = initial_query
    selected = 0

    while True:
        matches = fuzzy_match(repos, query)
        selected = min(selected, max(0, len(matches) - 1))
        screen.erase()
        height, width = screen.getmaxyx()
        screen.addnstr(0, 0, "Harness repos", max(1, width - 1))
        screen.addnstr(1, 0, f"> {query}", max(1, width - 1))

        visible_rows = max(1, height - 4)
        for row, repo in enumerate(matches[:visible_rows]):
            prefix = "›" if row == selected else " "
            text = f"{prefix} {repo.name:<22.22} {repo.branch:<18.18} {repo.display_path}"
            screen.addnstr(row + 2, 0, text, max(1, width - 1))

        footer = "type filter · ↑↓ move · enter launch · esc quit"
        screen.addnstr(height - 1, 0, footer, max(1, width - 1))
        screen.refresh()

        key = screen.get_wch()
        if key in ("\x1b", "\x03"):
            return None
        if key in ("\n", "\r", curses.KEY_ENTER):
            return matches[selected] if matches else None
        if key == curses.KEY_UP:
            selected = max(0, selected - 1)
            continue
        if key == curses.KEY_DOWN:
            selected = min(max(0, len(matches) - 1), selected + 1)
            continue
        if key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
            query = query[:-1]
            selected = 0
            continue
        if isinstance(key, str) and key.isprintable():
            query += key
            selected = 0


def _mark_used(repos: list[RepoEntry], selected: RepoEntry) -> list[RepoEntry]:
    now = time.time()
    return [
        RepoEntry(
            name=repo.name,
            path=repo.path,
            branch=repo.branch,
            remote=repo.remote,
            last_used=now if repo.path == selected.path else repo.last_used,
        )
        for repo in repos
    ]


def launch_repo(repo: RepoEntry) -> NoReturn:
    """Replace the picker with canonical ``fccdanger`` in the selected cwd."""

    os.chdir(repo.path)
    os.execvp("fccdanger", ["fccdanger"])
    raise AssertionError("os.execvp returned unexpectedly")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pick a local GitHub repo and launch fccdanger")
    parser.add_argument("query", nargs="?", default="", help="initial fuzzy filter")
    parser.add_argument("--refresh", action="store_true", help="force repository rescan")
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
    roots = tuple(Path(value).expanduser() for value in args.root) or default_roots()
    cache = cache_path()

    repos = [] if args.refresh else load_cached_repos(cache)
    if args.refresh or not repos or not cache_is_fresh(cache):
        previous_last_used = {repo.path: repo.last_used for repo in repos}
        repos = [
            RepoEntry(
                name=repo.name,
                path=repo.path,
                branch=repo.branch,
                remote=repo.remote,
                last_used=previous_last_used.get(repo.path, 0.0),
            )
            for repo in discover_repos(roots)
        ]
        save_cached_repos(repos, cache)

    if not repos:
        print("No local GitHub-backed repositories found.", file=sys.stderr)
        print("Try: fcc-repos --refresh --root ~/src", file=sys.stderr)
        raise SystemExit(1)

    selected = choose_repo(repos, args.query)
    if selected is None:
        return
    save_cached_repos(_mark_used(repos, selected), cache)
    launch_repo(selected)
