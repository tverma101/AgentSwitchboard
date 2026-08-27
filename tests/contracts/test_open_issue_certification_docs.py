"""Keep deterministic and live certification claims separate in docs."""

from pathlib import Path


def test_certification_docs_keep_live_work_explicit() -> None:
    text = Path("docs/OPEN_ISSUE_CERTIFICATION.md").read_text("utf-8")

    assert "Provider/device/literal-Claude work is never implied by a deterministic pass." in text
    assert "A missing live prerequisite\nis `unverified`, not `passed`." in text
    assert "scripts/compare_native_harness.py" in text
    assert "smoke/opencode_go_economics.py" in text
