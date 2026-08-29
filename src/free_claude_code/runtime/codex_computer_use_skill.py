"""Expose the installed official Codex Computer Use skill to Claude Code."""

import os
from collections.abc import Mapping
from pathlib import Path

from free_claude_code.runtime.codex_computer_use import (
    CodexComputerUseError,
    CodexComputerUsePaths,
)
from free_claude_code.runtime.codex_computer_use_managed import managed_plugin_root
from free_claude_code.runtime.codex_computer_use_native_contract import (
    SKILL_RELATIVE_PATH,
    read_native_computer_use_skill,
)

CLAUDE_SKILL_NAME = "computer-use"


def claude_config_dir_from_env(environment: Mapping[str, str] | None = None) -> Path:
    """Return Claude's active config root for the child launch environment."""

    values = os.environ if environment is None else environment
    configured = values.get("CLAUDE_CONFIG_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".claude"


def native_computer_use_skill_dir(paths: CodexComputerUsePaths) -> Path:
    """Return the bounded official skill directory after validating SKILL.md."""

    plugin_root = managed_plugin_root(paths)
    if plugin_root is None:
        raise CodexComputerUseError("bundled Computer Use plugin is unavailable")
    source = (plugin_root / SKILL_RELATIVE_PATH).parent.resolve()
    try:
        source.relative_to(plugin_root)
    except ValueError as error:
        raise CodexComputerUseError(
            "Computer Use skill directory escaped the bundled plugin root"
        ) from error
    read_native_computer_use_skill(paths)
    return source


def install_native_computer_use_skill(
    paths: CodexComputerUsePaths,
    *,
    claude_config_dir: Path,
) -> Path:
    """Install one source-owned skill symlink without overwriting user content."""

    source = native_computer_use_skill_dir(paths)
    skills_root = claude_config_dir.expanduser() / "skills"
    destination = skills_root / CLAUDE_SKILL_NAME

    if destination.is_symlink():
        try:
            current = destination.resolve(strict=True)
        except OSError as error:
            raise CodexComputerUseError(
                "existing Claude Computer Use skill symlink is broken"
            ) from error
        if current == source:
            return destination
        raise CodexComputerUseError(
            "Claude Computer Use skill path is already owned by another symlink"
        )
    if destination.exists():
        raise CodexComputerUseError(
            "Claude Computer Use skill path already exists; refusing to overwrite it"
        )

    skills_root.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source, target_is_directory=True)
    return destination


def remove_native_computer_use_skill(
    paths: CodexComputerUsePaths,
    *,
    claude_config_dir: Path,
) -> bool:
    """Remove only the exact FCC-created native skill link for this install."""

    destination = claude_config_dir.expanduser() / "skills" / CLAUDE_SKILL_NAME
    if not destination.is_symlink():
        return False
    try:
        current = destination.resolve(strict=True)
    except OSError:
        return False
    source = native_computer_use_skill_dir(paths)
    if current != source:
        return False
    destination.unlink()
    return True


__all__ = [
    "CLAUDE_SKILL_NAME",
    "claude_config_dir_from_env",
    "install_native_computer_use_skill",
    "native_computer_use_skill_dir",
    "remove_native_computer_use_skill",
]
