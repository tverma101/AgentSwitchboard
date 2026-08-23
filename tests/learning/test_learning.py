"""Tests for FCC Learning memory and Claude hook integration."""

import json
from pathlib import Path

from free_claude_code.learning.engine import apply_learning_result
from free_claude_code.learning.hooks import install_hooks, uninstall_hooks
from free_claude_code.learning.stop_hook import handle_stop
from free_claude_code.learning.store import LearningStore, format_memory_context


def test_store_deduplicates_and_scopes_memories(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / "learning.db")
    assert store.remember(
        scope="global",
        project_key="/repo",
        text="Prefer concise implementation notes.",
        confidence=0.95,
        source="user_explicit",
    )
    assert not store.remember(
        scope="global",
        project_key="/other",
        text="Prefer concise implementation notes.",
        confidence=0.99,
        source="user_explicit",
    )
    assert store.remember(
        scope="project",
        project_key="/repo",
        text="The project uses uv for Python dependencies.",
        confidence=0.96,
        source="verified_fact",
    )

    rows = store.relevant_memories(
        project_key="/repo", prompt="Which Python dependencies tool does this use?"
    )
    context = format_memory_context(rows)
    assert "Prefer concise implementation notes." in context
    assert "uses uv" in context

    other = format_memory_context(
        store.relevant_memories(project_key="/different", prompt="dependencies")
    )
    assert "uses uv" not in other
    assert "Prefer concise implementation notes." in other


def test_prompt_state_round_trip(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / "learning.db")
    store.record_prompt(session_id="session-1", cwd="/repo", prompt="Fix the parser")
    assert store.prompt_for_session("session-1") == ("/repo", "Fix the parser")


def test_hook_install_is_idempotent_and_preserves_existing_hooks(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "model": "haiku",
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "printf existing"}
                            ]
                        }
                    ]
                },
            }
        )
    )

    assert install_hooks(tmp_path)
    assert not install_hooks(tmp_path)

    payload = json.loads(settings.read_text())
    assert payload["model"] == "haiku"
    stop_commands = [
        hook["command"]
        for group in payload["hooks"]["Stop"]
        for hook in group["hooks"]
    ]
    assert "printf existing" in stop_commands
    assert any("free_claude_code.learning.stop_hook" in command for command in stop_commands)
    assert (tmp_path / "settings.json.fcc-learning.bak").exists()
    assert (tmp_path / "skills").is_dir()

    assert uninstall_hooks(tmp_path)
    restored = json.loads(settings.read_text())
    stop_commands = [
        hook["command"]
        for group in restored["hooks"]["Stop"]
        for hook in group["hooks"]
    ]
    assert stop_commands == ["printf existing"]
    assert "SessionStart" not in restored["hooks"]
    assert "UserPromptSubmit" not in restored["hooks"]


def test_apply_learning_result_rejects_low_confidence_and_writes_global_skill(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "fcc"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    store = LearningStore(tmp_path / "learning.db")

    result = {
        "memories": [
            {
                "scope": "global",
                "text": "Use uv for Python package management.",
                "confidence": 0.97,
                "evidence_kind": "user_explicit",
            },
            {
                "scope": "project",
                "text": "A temporary browser failure means browser tools never work.",
                "confidence": 0.4,
                "evidence_kind": "successful_workflow",
            },
        ],
        "skill": {
            "name": "verify-before-durable-learning",
            "description": "Validate durable learning before saving it.",
            "instructions": (
                "Check that the procedure actually succeeded. Reject temporary "
                "failures and unverified guesses. Save only reusable steps and "
                "include a concrete validation step before considering the skill complete."
            ),
            "scope": "global",
            "confidence": 0.97,
            "evidence_kind": "successful_workflow",
        },
    }

    counts = apply_learning_result(result=result, cwd=str(tmp_path), store=store)
    assert counts == {"memories": 1, "skills": 1}
    assert store.counts() == {"memories": 1, "skills": 1}
    skill = (
        tmp_path
        / "claude"
        / "skills"
        / "fcc-auto-verify-before-durable-learning"
        / "SKILL.md"
    )
    assert skill.exists()
    assert "temporary failures" in skill.read_text()


def test_project_skill_uses_repo_scope_without_leaking_local_path(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "personal-claude"))
    store = LearningStore(tmp_path / "learning.db")
    result = {
        "memories": [],
        "skill": {
            "name": "project-bootstrap",
            "description": "Reuse the verified project bootstrap procedure.",
            "instructions": (
                "Run the documented bootstrap command, verify dependencies resolve, "
                "then execute the project's smallest smoke test before continuing."
            ),
            "scope": "project",
            "confidence": 0.98,
            "evidence_kind": "successful_workflow",
        },
    }

    assert apply_learning_result(result=result, cwd=str(tmp_path), store=store) == {
        "memories": 0,
        "skills": 1,
    }
    learned = list((tmp_path / ".claude" / "skills").glob("fcc-auto-*/SKILL.md"))
    assert len(learned) == 1
    skill_text = learned[0].read_text()
    assert "Apply only within this repository." in skill_text
    assert str(tmp_path) not in skill_text
    assert not (tmp_path / "personal-claude" / "skills").exists()


def test_apply_learning_result_rejects_secret_like_memory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    store = LearningStore(tmp_path / "learning.db")
    result = {
        "memories": [
            {
                "scope": "global",
                "text": "API_KEY=supersecretvalue12345",
                "confidence": 0.99,
                "evidence_kind": "user_explicit",
            }
        ],
        "skill": None,
    }
    assert apply_learning_result(result=result, cwd=str(tmp_path), store=store) == {
        "memories": 0,
        "skills": 0,
    }


def test_stop_hook_ignores_missing_prompt_state(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / "learning.db")
    handle_stop(
        {
            "session_id": "unknown",
            "cwd": str(tmp_path),
            "last_assistant_message": "Completed successfully.",
        },
        store,
    )
    assert store.counts() == {"memories": 0, "skills": 0}
