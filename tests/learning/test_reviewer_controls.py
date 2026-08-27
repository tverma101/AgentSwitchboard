"""Coverage for profile-local reviewer controls and hook selection."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from free_claude_code.learning import cli as learning_cli
from free_claude_code.learning.reviewer_config import ReviewerPackSettings
from free_claude_code.learning.reviewer_flow import build_reviewer_plan, reviewer_status
from free_claude_code.learning.reviewer_scars import (
    PreventionClass,
    ReviewerPack,
    ScarCandidate,
    ScarKind,
    ScarRegistry,
    ScarState,
    admit_scar_candidate,
)


def _candidate(pack: ReviewerPack) -> ScarCandidate:
    return ScarCandidate(
        pack=pack,
        kind=ScarKind.CAVE,
        scope="native",
        condition="backend:absent",
        rule="check=registration;avoid=reinstall",
        state=ScarState.VERIFIED,
        prevention=PreventionClass.HOURS_DEBUGGING,
        evidence=("test:reviewer-controls",),
    )


def test_pack_settings_are_profile_isolated_and_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    coding = ReviewerPackSettings("coding")
    school = ReviewerPackSettings("school")

    assert coding.overrides() == {}
    coding.set_override(ReviewerPack.EDGE_CASES, False)
    assert coding.overrides() == {ReviewerPack.EDGE_CASES: False}
    assert school.overrides() == {}
    assert coding.path.stat().st_mode & 0o077 == 0


def test_reviewer_plan_honors_force_and_disable_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    registry = ScarRegistry("coding")
    registry.upsert(admit_scar_candidate(_candidate(ReviewerPack.REDUNDANCY)))
    settings = ReviewerPackSettings("coding")
    settings.set_override(ReviewerPack.REDUNDANCY, True)

    forced = build_reviewer_plan("plain text", profile="coding", registry=registry)
    assert forced.packs == (ReviewerPack.REDUNDANCY,)
    assert len(forced.selection.lines) == 1

    settings.set_override(ReviewerPack.REDUNDANCY, False)
    disabled = build_reviewer_plan(
        "cleanup new runtime", profile="coding", registry=registry
    )
    assert ReviewerPack.REDUNDANCY not in disabled.packs
    assert disabled.selection.lines == ()


def test_reviewer_status_and_cli_preserve_audit_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    registry = ScarRegistry("coding")
    registry.upsert(admit_scar_candidate(_candidate(ReviewerPack.EDGE_CASES)))
    scar_id = registry.load()[0].scar_id

    monkeypatch.setattr(
        sys,
        "argv",
        ["fcc-learning", "reviewer", "disable", "edge-cases", "--profile", "coding"],
    )
    learning_cli.main()
    assert json.loads(capsys.readouterr().out)["enabled"] is False

    status = reviewer_status(profile="coding")
    assert status["profile"] == "coding"
    assert any(pack["mode"] == "disabled" for pack in status["packs"])
    assert status["scars"][0]["scar_id"] == scar_id

    monkeypatch.setattr(
        sys,
        "argv",
        ["fcc-learning", "reviewer", "forget", scar_id, "--profile", "coding"],
    )
    learning_cli.main()
    updated = json.loads(capsys.readouterr().out)["updated"]
    assert updated["state"] == "STALE"
    assert updated["history"] == ["VERIFIED"]


def test_terminal_reviewer_menu_persists_pack_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    from free_claude_code.cli import terminal_control

    with patch("builtins.input", side_effect=["e", "edge-cases", "b"]):
        terminal_control._run_reviewer_menu("coding")

    assert ReviewerPackSettings("coding").overrides() == {ReviewerPack.EDGE_CASES: True}
    assert "Reviewer pack edge-cases: enabled" in capsys.readouterr().out
