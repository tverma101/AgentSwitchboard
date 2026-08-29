"""Tests for exposing the official Codex Computer Use skill to Claude."""

from pathlib import Path

import pytest

from free_claude_code.runtime.codex_computer_use import (
    CodexComputerUseError,
    CodexComputerUsePaths,
)
from free_claude_code.runtime.codex_computer_use_managed import PLUGIN_RELATIVE_PATH
from free_claude_code.runtime.codex_computer_use_native_contract import (
    SKILL_RELATIVE_PATH,
)
from free_claude_code.runtime.codex_computer_use_skill import (
    CLAUDE_SKILL_NAME,
    claude_config_dir_from_env,
    install_native_computer_use_skill,
    remove_native_computer_use_skill,
)


def _paths(tmp_path: Path) -> tuple[CodexComputerUsePaths, Path]:
    resources = tmp_path / "ChatGPT.app" / "Contents" / "Resources"
    codex = resources / "codex"
    codex.parent.mkdir(parents=True)
    codex.write_text("", encoding="utf-8")

    plugin_root = resources / PLUGIN_RELATIVE_PATH
    skill = plugin_root / SKILL_RELATIVE_PATH
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: computer-use\ndescription: Native Computer Use\n---\n",
        encoding="utf-8",
    )

    app = tmp_path / "Codex Computer Use.app"
    client = app / "Contents" / "MacOS" / "client"
    client.parent.mkdir(parents=True)
    client.write_text("", encoding="utf-8")
    return CodexComputerUsePaths(codex=codex, app=app, client=client), skill.parent


def test_claude_config_dir_uses_child_environment_and_default_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "profile" / "claude"
    assert (
        claude_config_dir_from_env({"CLAUDE_CONFIG_DIR": str(configured)}) == configured
    )

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert claude_config_dir_from_env({}) == tmp_path / ".claude"


def test_install_links_exact_official_skill_directory(tmp_path: Path) -> None:
    paths, source = _paths(tmp_path)
    claude = tmp_path / ".claude"

    destination = install_native_computer_use_skill(
        paths,
        claude_config_dir=claude,
    )

    assert destination == claude / "skills" / CLAUDE_SKILL_NAME
    assert destination.is_symlink()
    assert destination.resolve() == source.resolve()
    assert (destination / "SKILL.md").read_text(encoding="utf-8").startswith("---\n")


def test_install_is_idempotent_for_our_exact_link(tmp_path: Path) -> None:
    paths, _source = _paths(tmp_path)
    claude = tmp_path / ".claude"

    first = install_native_computer_use_skill(paths, claude_config_dir=claude)
    second = install_native_computer_use_skill(paths, claude_config_dir=claude)

    assert first == second
    assert first.is_symlink()


def test_install_refuses_user_owned_directory(tmp_path: Path) -> None:
    paths, _source = _paths(tmp_path)
    destination = tmp_path / ".claude" / "skills" / CLAUDE_SKILL_NAME
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_text("user owned", encoding="utf-8")

    with pytest.raises(CodexComputerUseError, match="refusing to overwrite"):
        install_native_computer_use_skill(
            paths,
            claude_config_dir=tmp_path / ".claude",
        )

    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "user owned"


def test_install_refuses_other_symlink_owner(tmp_path: Path) -> None:
    paths, _source = _paths(tmp_path)
    other = tmp_path / "other-skill"
    other.mkdir()
    destination = tmp_path / ".claude" / "skills" / CLAUDE_SKILL_NAME
    destination.parent.mkdir(parents=True)
    destination.symlink_to(other, target_is_directory=True)

    with pytest.raises(CodexComputerUseError, match="another symlink"):
        install_native_computer_use_skill(
            paths,
            claude_config_dir=tmp_path / ".claude",
        )

    assert destination.resolve() == other.resolve()


def test_remove_only_unlinks_exact_owned_skill(tmp_path: Path) -> None:
    paths, _source = _paths(tmp_path)
    claude = tmp_path / ".claude"
    destination = install_native_computer_use_skill(paths, claude_config_dir=claude)

    assert remove_native_computer_use_skill(paths, claude_config_dir=claude) is True
    assert not destination.exists()
    assert not destination.is_symlink()
    assert remove_native_computer_use_skill(paths, claude_config_dir=claude) is False


def test_remove_preserves_foreign_symlink(tmp_path: Path) -> None:
    paths, _source = _paths(tmp_path)
    claude = tmp_path / ".claude"
    other = tmp_path / "other-skill"
    other.mkdir()
    destination = claude / "skills" / CLAUDE_SKILL_NAME
    destination.parent.mkdir(parents=True)
    destination.symlink_to(other, target_is_directory=True)

    assert remove_native_computer_use_skill(paths, claude_config_dir=claude) is False
    assert destination.is_symlink()
    assert destination.resolve() == other.resolve()
