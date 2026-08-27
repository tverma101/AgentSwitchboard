"""Loopback Admin coverage for reviewer pack and scar controls."""

from pathlib import Path

from fastapi.testclient import TestClient

from free_claude_code.learning.reviewer_scars import (
    PreventionClass,
    ReviewerPack,
    ScarCandidate,
    ScarKind,
    ScarRegistry,
    ScarState,
    admit_scar_candidate,
)
from tests.api.support import create_test_app


def _local_client(app) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 50000))


def _candidate() -> ScarCandidate:
    return ScarCandidate(
        pack=ReviewerPack.EDGE_CASES,
        kind=ScarKind.CAVE,
        scope="macos",
        condition="permission:missing",
        rule="check=accessibility;avoid=claim-live",
        state=ScarState.VERIFIED,
        prevention=PreventionClass.FALSE_COMPLETION,
        evidence=("test:reviewer-admin",),
    )


def test_reviewer_admin_controls_are_loopback_only_and_auditable(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    monkeypatch.delenv("FCC_LEARNING_PROFILE", raising=False)

    registry = ScarRegistry()
    registry.upsert(admit_scar_candidate(_candidate()))
    scar_id = registry.load()[0].scar_id
    app = create_test_app()
    client = _local_client(app)

    status = client.get("/admin/api/reviewer")
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["profile"] == "default"
    assert status.json()["scars"][0]["scar_id"] == scar_id

    disabled = client.put(
        "/admin/api/reviewer/packs/edge-cases",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert (
        next(pack for pack in disabled.json()["packs"] if pack["pack"] == "edge-cases")[
            "mode"
        ]
        == "disabled"
    )

    forgotten = client.post(f"/admin/api/reviewer/scars/{scar_id}/forget")
    assert forgotten.status_code == 200
    assert forgotten.json()["state"] == "STALE"
    assert forgotten.json()["history"] == ["VERIFIED"]

    remote = TestClient(app, client=("203.0.113.10", 50000))
    assert remote.get("/admin/api/reviewer").status_code == 403


def test_reviewer_admin_reports_unknown_scar_without_mutating_state(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    response = _local_client(create_test_app()).post(
        "/admin/api/reviewer/scars/not-a-real-scar/supersede"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Reviewer scar not found"
