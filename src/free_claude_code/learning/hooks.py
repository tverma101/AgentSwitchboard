"""Claude Code hook installation for the optional FCC project-memory layer."""

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from .config import learning_enabled
from .memory_context import select_bounded_memory_context
from .store import LearningStore, project_identity

_HOOK_MODULE = "free_claude_code.learning.cli"
_LEGACY_STOP_HOOK_MODULE = "free_claude_code.learning.stop_hook"
_HOOK_EVENTS: dict[str, tuple[str, int]] = {
    "SessionStart": ("session-start", 10),
}


def _hook_definition(event: str) -> dict[str, Any]:
    hook_name, timeout = _HOOK_EVENTS[event]
    return {
        "type": "command",
        "command": f"{shlex.quote(sys.executable)} -m {_HOOK_MODULE} hook {hook_name}",
        "timeout": timeout,
    }


def claude_config_dir() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def _settings_path(config_dir: Path | None = None) -> Path:
    return (config_dir or claude_config_dir()) / "settings.json"


def _load_settings(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"cannot safely update invalid Claude settings: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Claude settings root must be a JSON object: {path}")
    return payload


def _is_our_hook(hook: object) -> bool:
    if not isinstance(hook, dict):
        return False
    command = hook.get("command")
    if not isinstance(command, str):
        return False
    return (
        f"-m {_HOOK_MODULE} hook " in command
        or f"-m {_LEGACY_STOP_HOOK_MODULE}" in command
    )


def _strip_legacy_runtime_hooks(hooks: dict[str, Any]) -> bool:
    """Remove obsolete FCC prompt/agent/turn hooks while preserving user hooks."""

    expected = _hook_definition("SessionStart")
    changed = False
    for event in list(hooks):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        new_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                new_groups.append(group)
                continue
            filtered: list[Any] = []
            for candidate in group["hooks"]:
                keep_current = (
                    event == "SessionStart"
                    and group.get("matcher") is None
                    and candidate == expected
                )
                if _is_our_hook(candidate) and not keep_current:
                    changed = True
                    continue
                filtered.append(candidate)
            if filtered:
                replacement = dict(group)
                replacement["hooks"] = filtered
                new_groups.append(replacement)
        if new_groups:
            hooks[event] = new_groups
        elif groups:
            hooks.pop(event, None)
    return changed


def install_hooks(config_dir: Path | None = None) -> bool:
    """Install only the project-memory SessionStart hook.

    FCC does not own Claude's prompts, live steering, agents, subagents, or turn
    lifecycle. Installing the memory layer also removes older FCC runtime hooks
    that intercepted those Claude-owned surfaces.
    """

    root = config_dir or claude_config_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = _settings_path(root)
    settings = _load_settings(path)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Claude settings 'hooks' value must be an object")

    changed = _strip_legacy_runtime_hooks(hooks)
    expected = _hook_definition("SessionStart")
    groups = hooks.setdefault("SessionStart", [])
    if not isinstance(groups, list):
        raise ValueError("Claude settings hooks.SessionStart must be an array")

    found = any(
        isinstance(group, dict)
        and group.get("matcher") is None
        and isinstance(group.get("hooks"), list)
        and expected in group["hooks"]
        for group in groups
    )
    if not found:
        groups.append({"hooks": [dict(expected)]})
        changed = True

    if not changed:
        return False
    if path.exists():
        backup = path.with_name("settings.json.fcc-learning.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return True


def uninstall_hooks(config_dir: Path | None = None) -> bool:
    """Remove every FCC Learning hook while preserving unrelated settings."""

    path = _settings_path(config_dir)
    if not path.exists():
        return False
    settings = _load_settings(path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False

    changed = False
    for event in list(hooks):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        new_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                new_groups.append(group)
                continue
            filtered = [hook for hook in group["hooks"] if not _is_our_hook(hook)]
            if len(filtered) != len(group["hooks"]):
                changed = True
            if filtered:
                replacement = dict(group)
                replacement["hooks"] = filtered
                new_groups.append(replacement)
        if new_groups:
            hooks[event] = new_groups
        elif groups:
            hooks.pop(event, None)

    if not changed:
        return False
    if not hooks:
        settings.pop("hooks", None)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return True


def ensure_learning_hooks() -> None:
    """Reconcile the optional project-memory hook with its opt-in setting."""

    if learning_enabled():
        install_hooks()
    else:
        uninstall_hooks()


def _read_hook_input() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError, OSError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _emit_hook_context(event: str, context: str) -> None:
    output: dict[str, Any] = {"hookSpecificOutput": {"hookEventName": event}}
    specific: dict[str, Any] = output["hookSpecificOutput"]
    if context:
        specific["additionalContext"] = context
    print(json.dumps(output))


def handle_session_start(payload: dict[str, Any], store: LearningStore) -> None:
    """Inject one bounded project-memory context at the native session boundary."""

    cwd = str(payload.get("cwd") or os.getcwd())
    project_key = project_identity(cwd)
    rows = store.relevant_memories(project_key=project_key, limit=12)
    context = f"FCC project memory profile: {store.profile}."
    selection = select_bounded_memory_context(rows, profile=store.profile)
    if selection.text:
        context = f"{context}\n{selection.text}"
        store.mark_memories_used(selection.memory_ids)
    _emit_hook_context("SessionStart", context)


def run_hook(event: str, *, profile: str | None = None) -> None:
    """Run one lightweight Claude-owned lifecycle hook from JSON stdin."""

    if not learning_enabled():
        return
    if event != "session-start":
        raise ValueError(f"unknown FCC project-memory hook: {event}")
    handle_session_start(_read_hook_input(), LearningStore(profile=profile))
