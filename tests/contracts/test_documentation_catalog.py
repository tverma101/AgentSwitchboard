"""Keep the documentation catalogue complete and discoverable."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "docs" / "README.md"
IGNORED_DIRECTORIES = {
    ".git",
    ".claude",
    ".pytest_cache",
    ".project-memory",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


def _markdown_paths() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.md")
        if not any(part in IGNORED_DIRECTORIES for part in path.parts)
    )


def test_documentation_catalogue_lists_every_markdown_file() -> None:
    catalogue = CATALOGUE.read_text(encoding="utf-8")
    missing = [path for path in _markdown_paths() if f"`{path}`" not in catalogue]

    assert not missing, "Markdown files missing from docs/README.md:\n" + "\n".join(
        missing
    )
