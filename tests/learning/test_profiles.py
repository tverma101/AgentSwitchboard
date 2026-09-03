"""Tests for explicit FCC Learning profile selection and isolation."""

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from free_claude_code.cli.launchers import claude
from free_claude_code.learning import cli as learning_cli
from free_claude_code.learning.config import (
    LearningProfileError,
    archive_profile,
    create_profile,
    extract_profile_argument,
    list_archived_profiles,
    list_profiles,
    profile_database,
    profile_home,
    rename_profile,
    restore_profile,
)
from free_claude_code.learning.engine import apply_learning_result
from free_claude_code.learning.hooks import run_hook
from free_claude_code.learning.store import LearningStore


def _skill_result() -> dict[str, object]:
    return {
        "memory_actions": [],
        "skill": {
            "action": "create",
            "name": "profile-workflow",
            "description": "Use the selected profile workflow.",
            "instructions": (
                "Run the focused tests, verify the diff, and check the final "
                "status before handoff."
            ),
            "scope": "global",
            "confidence": 0.98,
            "evidence_kind": "successful_workflow",
        },
    }


def test_named_profiles_isolate_memory_databases_and_generated_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    default = LearningStore(profile="default")
    coding = LearningStore(profile="coding")
    assert default.path == tmp_path / "learning" / "learning.db"
    assert coding.path == tmp_path / "learning" / "profiles" / "coding" / "learning.db"
    assert default.path != coding.path

    assert default.remember(
        scope="global",
        project_key=str(tmp_path),
        text="Default profile preference.",
        confidence=0.98,
        source="user_explicit",
    )
    assert coding.remember(
        scope="global",
        project_key=str(tmp_path),
        text="Default profile preference.",
        confidence=0.98,
        source="user_explicit",
    )
    assert default.counts() == {"memories": 1, "skills": 0}
    assert coding.counts() == {"memories": 1, "skills": 0}

    assert apply_learning_result(
        result=_skill_result(), cwd=str(tmp_path), store=coding
    ) == {"memories": 0, "skills": 1}
    coding_skill = (
        tmp_path / "claude" / "skills" / "fcc-coding-auto-profile-workflow" / "SKILL.md"
    )
    assert coding_skill.exists()
    assert not (
        tmp_path / "claude" / "skills" / "fcc-auto-profile-workflow" / "SKILL.md"
    ).exists()
    assert coding.skill_record("fcc-coding-auto-profile-workflow") is not None


def test_hooks_use_explicit_profile_and_advertise_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FCC_LEARNING_ENABLED", "1")
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    coding = LearningStore(profile="coding")
    coding.remember(
        scope="global",
        project_key=str(tmp_path),
        text="Coding profile memory.",
        confidence=0.98,
        source="user_explicit",
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"cwd": str(tmp_path)})),
    )

    run_hook("session-start", profile="coding")

    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "FCC project memory profile: coding." in context
    assert "Coding profile memory." in context
    assert LearningStore(profile="default").counts() == {"memories": 0, "skills": 0}


def test_learning_cli_selects_profile_for_status_and_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    coding = LearningStore(profile="coding")
    memory_id, _ = coding.add_memory(
        scope="global",
        project_key=str(tmp_path),
        text="Coding-only memory.",
        confidence=0.98,
        source="user_explicit",
    )

    def run(*args: str) -> Any:
        monkeypatch.setattr(sys, "argv", ["fcc-learning", *args])
        learning_cli.main()
        return json.loads(capsys.readouterr().out)

    status = run("status", "--profile", "coding")
    assert status["profile"] == "coding"
    assert status["profile_version"] == 1
    assert status["memories"] == 1
    assert "profiles/coding/learning.db" in status["database"]
    rows = run(
        "memory",
        "list",
        "--cwd",
        str(tmp_path),
        "--profile",
        "coding",
    )
    assert rows[0]["id"] == memory_id
    assert run("status", "--profile", "default")["memories"] == 0


def test_launcher_profile_is_removed_from_claude_args_and_inherited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        anthropic_auth_token="proxy-token",
        claude_known_good_version="2.1.228",
        claude_allow_uncertified=False,
        claude_process_wrapper_path="",
    )
    monkeypatch.setenv("FCC_LEARNING_PROFILE", "default")
    with (
        patch.object(
            claude, "extract_profile_argument", wraps=extract_profile_argument
        ),
        patch.object(claude, "get_settings", return_value=settings),
        patch.object(
            claude, "local_proxy_root_url", return_value="http://127.0.0.1:8082"
        ),
        patch.object(claude, "preflight_proxy", return_value=None),
        patch.object(claude, "ensure_learning_hooks"),
        patch.object(claude, "resolve_client_binary", return_value="resolved-claude"),
        patch.object(
            claude, "settings_env_routing_conflict_message", return_value=None
        ),
        patch.object(claude, "default_process_wrapper_path", return_value="wrapper"),
        patch.object(claude.os.path, "isfile", return_value=False),
        patch.object(claude, "build_claude_proxy_env", return_value={}) as build_env,
        patch.object(claude, "run_client_process", side_effect=SystemExit(0)) as run,
        pytest.raises(SystemExit) as exc_info,
    ):
        claude.launch(["--profile", "coding", "--model", "sonnet"])

    assert exc_info.value.code == 0
    assert run.call_args.kwargs["command"] == [
        "resolved-claude",
        "--model",
        "sonnet",
    ]
    assert os.environ["FCC_LEARNING_PROFILE"] == "default"
    child_base_env = build_env.call_args.kwargs["base_env"]
    assert child_base_env["FCC_LEARNING_PROFILE"] == "coding"
    assert child_base_env["CLAUDE_CODE_EFFORT_LEVEL"] == "xhigh"


def test_server_profile_option_selects_learning_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from free_claude_code.cli import entrypoints

    monkeypatch.delenv("FCC_LEARNING_PROFILE", raising=False)
    with patch.object(entrypoints, "_run_server_entrypoint") as run:
        entrypoints.serve(["--profile", "school"])

    run.assert_called_once_with()
    assert os.environ["FCC_LEARNING_PROFILE"] == "school"
    os.environ.pop("FCC_LEARNING_PROFILE", None)


def test_profile_arguments_reject_invalid_and_duplicate_values() -> None:
    assert extract_profile_argument(["--model", "sonnet", "--profile=coding"]) == (
        ["--model", "sonnet"],
        "coding",
    )
    with pytest.raises(LearningProfileError):
        extract_profile_argument(["--profile", "../unsafe"])
    with pytest.raises(LearningProfileError, match="only once"):
        extract_profile_argument(["--profile", "coding", "--profile", "coding"])


def test_profile_lifecycle_preserves_state_and_uses_recovery_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    monkeypatch.delenv("FCC_LEARNING_PROFILE", raising=False)

    assert list_profiles() == ("default",)
    assert create_profile(" Coding ") == "coding"
    assert list_profiles() == ("coding", "default")
    coding = LearningStore(profile="coding")
    coding.remember(
        scope="global",
        project_key=str(tmp_path),
        text="Keep coding state isolated.",
        confidence=0.98,
        source="user_explicit",
    )

    with pytest.raises(LearningProfileError, match="already exists"):
        create_profile("coding")
    with pytest.raises(LearningProfileError, match="default"):
        rename_profile("default", "school")
    with pytest.raises(LearningProfileError, match="differ"):
        rename_profile("coding", "coding")

    assert rename_profile("coding", "school") == "school"
    assert not profile_home("coding").exists()
    assert profile_database("school").exists()
    assert LearningStore(profile="school").counts() == {"memories": 1, "skills": 0}

    monkeypatch.setenv("FCC_LEARNING_PROFILE", "school")
    with pytest.raises(LearningProfileError, match="active"):
        archive_profile("school")
    monkeypatch.delenv("FCC_LEARNING_PROFILE")

    assert archive_profile("school") == "school"
    assert not profile_home("school").exists()
    assert list_profiles() == ("default",)
    assert list_archived_profiles() == ("school",)
    assert restore_profile("school") == "school"
    assert list_profiles() == ("default", "school")
    assert list_archived_profiles() == ()
    assert LearningStore(profile="school").counts() == {"memories": 1, "skills": 0}


def test_profile_lifecycle_cli_surfaces_active_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FCC_LEARNING_HOME", str(tmp_path / "learning"))
    monkeypatch.delenv("FCC_LEARNING_PROFILE", raising=False)

    def run(*args: str) -> dict[str, Any]:
        monkeypatch.setattr(sys, "argv", ["fcc-learning", *args])
        learning_cli.main()
        return json.loads(capsys.readouterr().out)

    assert run("profile", "create", "research") == {"created": "research"}
    listed = run("profile", "list")
    assert listed["active_profile"] == "default"
    assert [row["profile"] for row in listed["profiles"]] == [
        "default",
        "research",
    ]
    assert listed["profiles"][0]["active"] is True
    assert listed["profiles"][1]["active"] is False
