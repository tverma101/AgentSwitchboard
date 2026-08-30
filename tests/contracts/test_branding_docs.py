"""Keep current user-facing documentation on the AgentSwitchboard brand."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "ARCHITECTURE.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "UPSTREAM.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    ROOT / "smoke" / "README.md",
    ROOT / ".github" / "ISSUE_TEMPLATE" / "bug-report.yml",
    ROOT / ".github" / "ISSUE_TEMPLATE" / "feature-request.yml",
    ROOT / "assets" / "how-it-works.mmd",
    ROOT / "assets" / "agent-switchboard-wordmark-dark.svg",
    ROOT / "assets" / "agent-switchboard-wordmark-light.svg",
    ROOT
    / "src"
    / "free_claude_code"
    / "cli"
    / "_vendor"
    / "openai_screenshot"
    / "SOURCE.md",
    *sorted((ROOT / "docs").glob("*.md")),
)
LEGACY_PRODUCT_NAME = re.compile(r"\bHarness\b")
LEGACY_UPSTREAM_NAME = "Free Claude Code"
UPSTREAM_REFERENCE_DOCUMENTS = {
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "UPSTREAM.md",
}


def test_user_facing_docs_use_agentswitchboard_brand() -> None:
    missing_brand = [
        str(document.relative_to(ROOT))
        for document in DOCUMENTS
        if "AgentSwitchboard" not in document.read_text(encoding="utf-8")
    ]
    assert not missing_brand, "missing AgentSwitchboard brand: " + ", ".join(
        missing_brand
    )


def test_user_facing_docs_do_not_present_harness_as_the_product() -> None:
    stale_brand = [
        str(document.relative_to(ROOT))
        for document in DOCUMENTS
        if LEGACY_PRODUCT_NAME.search(document.read_text(encoding="utf-8"))
    ]
    assert not stale_brand, "stale Harness product references: " + ", ".join(
        stale_brand
    )


def test_free_claude_code_only_appears_in_upstream_references() -> None:
    stale_brand = [
        str(document.relative_to(ROOT))
        for document in DOCUMENTS
        if LEGACY_UPSTREAM_NAME in document.read_text(encoding="utf-8")
        and document not in UPSTREAM_REFERENCE_DOCUMENTS
    ]
    assert not stale_brand, "stale current-brand references: " + ", ".join(stale_brand)
