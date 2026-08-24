"""Keep user-facing Markdown links valid inside the repository."""

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\s]+)")
DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "ARCHITECTURE.md",
    ROOT / "CONTRIBUTING.md",
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
