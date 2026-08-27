"""Keep user-facing Markdown links valid inside the repository."""

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\s]+)")
PROJECT_VERSION = re.compile(r'^version = "(?P<version>[^\"]+)"$', re.MULTILINE)
DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "ARCHITECTURE.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "UPSTREAM.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    *sorted((ROOT / "docs").glob("*.md")),
    ROOT / "smoke" / "README.md",
)


def test_user_facing_markdown_links_resolve() -> None:
    missing: list[str] = []
    for document in DOCUMENTS:
        contents = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(contents):
            target = unquote(raw_target.split("#", 1)[0])
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{document.relative_to(ROOT)} -> {raw_target}")

    assert not missing, "broken internal Markdown links:\n" + "\n".join(missing)


def test_readme_release_version_matches_project_metadata() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version_match = PROJECT_VERSION.search(pyproject)
    assert version_match is not None

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    version = version_match.group("version")
    assert f"local release head is version\n`{version}`" in readme


def test_user_facing_docs_use_the_current_compact_receipt_name() -> None:
    documents = (ROOT / "README.md", *(ROOT / "docs").glob("*.md"))
    stale_reference = "muse-auto-compact-2026-08-23"
    assert all(
        stale_reference not in document.read_text(encoding="utf-8")
        for document in documents
    )
