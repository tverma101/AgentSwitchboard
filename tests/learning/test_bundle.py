"""Tests for the portable FCC Learning bundle contract."""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from free_claude_code.learning import cli as learning_cli
from free_claude_code.learning.bundle import (
    BundleError,
    build_bundle,
    export_from_store,
    import_bundle,
    inspect_bundle,
    read_bundle,
)
from free_claude_code.learning.store import LearningStore


def _seed_store(
    root: Path, database_path: Path | None = None
) -> tuple[LearningStore, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    project = root / "source-project"
    project.mkdir()
    store = LearningStore(database_path or root / "source-learning.db")
    store.add_memory(
        scope="global",
        project_key=str(project),
        text=f"Keep the verified notes under {project}.",
        confidence=0.97,
        source="user_explicit",
    )
    store.add_memory(
        scope="project",
        project_key=str(project),
        text=f"Run the focused checks from {project} before handoff.",
        confidence=0.96,
        source="successful_workflow",
    )
    skill_key = "fcc-auto-review-work"
    skill_path = root / "claude" / "skills" / skill_key / "SKILL.md"
    skill_content = (
        "---\n"
        f"name: {skill_key}\n"
        'description: "Review the work before handoff."\n'
        "---\n\n"
        "# Review work\n\n"
        "Run the focused tests, verify the diff, and check the final status.\n"
    )
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(skill_content, encoding="utf-8")
    digest = store.record_skill_revision(
        skill_key=skill_key, revision=2, content=skill_content
    )
    store.record_skill(
        skill_key=skill_key,
        path=skill_path,
        scope="global",
        project_key="",
        description="Review the work before handoff.",
        revision=2,
        digest=digest,
    )
    return store, project, skill_path


def test_export_is_deterministic_and_has_no_source_path(tmp_path: Path) -> None:
    store, project, _ = _seed_store(tmp_path)
    first = tmp_path / "first.bundle"
    second = tmp_path / "second.bundle"

    first_summary = export_from_store(
        first,
        store=store,
        project_key=str(project),
        profile="Coding",
    )
    export_from_store(
        second,
        store=store,
        project_key=str(project),
        profile="Coding",
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_summary["profile"] == "coding"
    assert first_summary["memories"] == 2
    assert first_summary["skills"] == 1
    assert str(project).encode() not in first.read_bytes()
    bundle = read_bundle(first)
    assert bundle.manifest["memories"][0]["project_ref"] in {"global", "current"}
    assert b"<project>" in json.dumps(bundle.manifest).encode()
    assert inspect_bundle(first) == first_summary


def test_import_dry_run_round_trip_and_explicit_skill_conflicts(
    tmp_path: Path,
) -> None:
    source_store, source_project, _ = _seed_store(tmp_path / "source")
    bundle_path = tmp_path / "portable.bundle"
    export_from_store(
        bundle_path,
        store=source_store,
        project_key=str(source_project),
        profile="coding",
    )

    target_project = tmp_path / "target-project"
    target_project.mkdir()
    target_store = LearningStore(tmp_path / "target-learning.db")
    target_claude = tmp_path / "target-claude"
    dry_run = import_bundle(
        bundle_path,
        store=target_store,
        target_project_key=str(target_project),
        claude_config_dir=target_claude,
        dry_run=True,
    )
    assert dry_run["dry_run"] is True
    assert {action["action"] for action in dry_run["actions"]} == {"add"}
    assert target_store.counts() == {"memories": 0, "skills": 0}
    assert not (target_claude / "skills").exists()

    applied = import_bundle(
        bundle_path,
        store=target_store,
        target_project_key=str(target_project),
        claude_config_dir=target_claude,
    )
    assert applied["applied"] == {"memories": 2, "skills": 1}
    assert target_store.counts() == {"memories": 2, "skills": 1}
    target_skill = target_claude / "skills" / "fcc-auto-review-work" / "SKILL.md"
    assert target_skill.exists()
    assert str(target_project) in next(
        row["text"]
        for row in target_store.list_memories(project_key=str(target_project))
        if row["scope"] == "project"
    )

    repeated = import_bundle(
        bundle_path,
        store=target_store,
        target_project_key=str(target_project),
        claude_config_dir=target_claude,
    )
    assert repeated["applied"] == {"memories": 0, "skills": 0}
    assert {action["action"] for action in repeated["actions"]} == {
        "skip_duplicate",
        "skip_unchanged",
    }

    target_skill.write_text(target_skill.read_text() + "\nChanged locally.\n")
    conflict_plan = import_bundle(
        bundle_path,
        store=target_store,
        target_project_key=str(target_project),
        claude_config_dir=target_claude,
        conflict="fail",
        dry_run=True,
    )
    assert "conflict" in {action["action"] for action in conflict_plan["actions"]}
    replaced = import_bundle(
        bundle_path,
        store=target_store,
        target_project_key=str(target_project),
        claude_config_dir=target_claude,
        conflict="replace",
    )
    assert replaced["applied"] == {"memories": 0, "skills": 1}
    assert "Changed locally" not in target_skill.read_text()
    assert len(target_store.skill_revisions("fcc-auto-review-work")) == 2


def test_bundle_rejects_unknown_version_tampering_and_secret_sources(
    tmp_path: Path,
) -> None:
    store, project, _ = _seed_store(tmp_path / "seed")
    path = tmp_path / "portable.bundle"
    export_from_store(path, store=store, project_key=str(project))
    original = read_bundle(path)
    tampered = io.BytesIO()
    manifest = dict(original.manifest)
    manifest["version"] = 99
    with zipfile.ZipFile(tampered, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, content in original.files.items():
            archive.writestr(name, content)
    path.write_bytes(tampered.getvalue())
    with pytest.raises(BundleError, match="unsupported learning bundle version"):
        read_bundle(path)

    unsafe = tmp_path / "unsafe.bundle"
    with pytest.raises(BundleError, match="secret-like"):
        build_bundle(
            profile="default",
            project_key=str(project),
            memories=[
                {
                    "scope": "global",
                    "project_key": "",
                    "text": "API_KEY=not-safe-value-12345",
                    "confidence": 0.99,
                    "source": "user_explicit",
                    "pinned": True,
                }
            ],
            skills=[],
            skill_contents={},
        )
    assert not unsafe.exists()


def test_bundle_cli_export_inspect_and_dry_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    learning_home = tmp_path / "cli-home"
    monkeypatch.setenv("FCC_LEARNING_HOME", str(learning_home))
    learning_home.mkdir()
    _, project, _ = _seed_store(tmp_path / "cli", learning_home / "learning.db")
    bundle_path = tmp_path / "cli.bundle"

    def run(*args: str) -> dict[str, object]:
        monkeypatch.setattr(sys, "argv", ["fcc-learning", *args])
        learning_cli.main()
        return json.loads(capsys.readouterr().out)

    exported = run(
        "bundle",
        "export",
        str(bundle_path),
        "--cwd",
        str(project),
        "--profile",
        "coding",
    )
    assert exported["profile"] == "coding"
    inspected = run("bundle", "inspect", str(bundle_path))
    assert inspected == exported
    planned = run(
        "bundle",
        "import",
        str(bundle_path),
        "--cwd",
        str(tmp_path / "new-project"),
        "--dry-run",
    )
    assert planned["dry_run"] is True
