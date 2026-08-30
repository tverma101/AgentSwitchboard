"""Claude Code hook installation and lightweight event handlers for FCC Learning."""

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from .auto_reviewer import augment_agent_input
from .config import learning_enabled
from .delegated_worker import (
    claude_agent_posttool_event,
    claude_subagent_stop_event,
)
from .reviewer_flow import reviewer_context_for_task
from .stop_hook import spawn_queue_worker
from .store import LearningStore, format_memory_context, project_identity
from .worker_reviewer import process_background_worker_stop, process_worker_event

_HOOK_MODULE = "free_claude_code.learning.cli"
_STOP_HOOK_MODULE = "free_claude_code.learning.stop_hook"
_HOOK_EVENTS: dict[str, tuple[str, int, bool]] = {
    "SessionStart": ("session-start", 10, False),
    "UserPromptSubmit": ("user-prompt", 10, False),
    "PreToolUse": ("agent-pre", 10, False),
    "PostToolUse": ("agent-post", 10, False),
    "SubagentStart": ("subagent-start", 10, False),
    "SubagentStop": ("subagent-stop", 10, False),
    "Stop": ("stop", 60, True),
}
_HOOK_MATCHERS = {
    "PreToolUse": "Agent",
    "PostToolUse": "Agent",
}


def _hook_definition(event: str) -> dict[str, Any]:
    hook_name, timeout, asynchronous = _HOOK_EVENTS[event]
    if event == "Stop":
        command = f"{shlex.quote(sys.executable)} -m {_STOP_HOOK_MODULE}"
    else:
        command = f"{shlex.quote(sys.executable)} -m {_HOOK_MODULE} hook {hook_name}"
    hook: dict[str, Any] = {
        "type": "command",
        "command": command,
        "timeout": timeout,
    }
    if asynchronous:
        hook["async"] = True
    return hook


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
    if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
        return False
    command = hook.get("command")
    if not isinstance(command, str):
        return False
    return f"-m {_HOOK_MODULE} hook " in command or f"-m {_STOP_HOOK_MODULE}" in command


def install_hooks(config_dir: Path | None = None) -> bool:
    """Merge FCC hooks into Claude settings without replacing user hooks."""

    root = config_dir or claude_config_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    path = _settings_path(root)
    settings = _load_settings(path)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Claude settings 'hooks' value must be an object")

    changed = False
    for event in _HOOK_EVENTS:
        expected = _hook_definition(event)
        expected_matcher = _HOOK_MATCHERS.get(event)
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"Claude settings hooks.{event} must be an array")

        found = False
        for group in groups:
            if not isinstance(group, dict):
                continue
            if (
                expected_matcher is not None
                and group.get("matcher") != expected_matcher
            ):
                continue
            candidates = group.get("hooks")
            if not isinstance(candidates, list):
                continue
            for index, candidate in enumerate(candidates):
                if _is_our_hook(candidate):
                    found = True
                    if candidate != expected:
                        candidates[index] = dict(expected)
                        changed = True
        if not found:
            group: dict[str, Any] = {"hooks": [dict(expected)]}
            if expected_matcher is not None:
                group["matcher"] = expected_matcher
            groups.append(group)
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
    """Remove only FCC Learning hooks, preserving every unrelated setting."""

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
    """Reconcile FCC Learning hooks with the explicit opt-in setting."""

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


def _emit_hook_context(
    event: str, context: str, *, reload_skills: bool = False
) -> None:
    output: dict[str, Any] = {"hookSpecificOutput": {"hookEventName": event}}
    specific: dict[str, Any] = output["hookSpecificOutput"]
    if context:
        specific["additionalContext"] = context
    if reload_skills:
        specific["reloadSkills"] = True
    print(json.dumps(output))


def _emit_updated_input(updated_input: dict[str, object]) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": updated_input,
                }
            }
        )
    )


def _emit_empty_hook_result() -> None:
    print("{}")


def handle_session_start(payload: dict[str, Any], store: LearningStore) -> None:
    cwd = str(payload.get("cwd") or os.getcwd())
    project_key = project_identity(cwd)
    rows = store.relevant_memories(project_key=project_key, limit=12)
    context = f"FCC Learning active profile: {store.profile}."
    memory_context = format_memory_context(rows, profile=store.profile)
    if memory_context:
        context = f"{context}\n{memory_context}"
    _emit_hook_context(
        "SessionStart",
        context,
        reload_skills=True,
    )
    queue_counts = store.queue_counts()
    if queue_counts.get("pending", 0) or queue_counts.get("processing", 0):
        spawn_queue_worker(profile=store.profile)


def handle_user_prompt(payload: dict[str, Any], store: LearningStore) -> None:
    session_id = str(payload.get("session_id") or "")
    cwd = str(payload.get("cwd") or os.getcwd())
    prompt = payload.get("prompt")
    prompt_text = prompt if isinstance(prompt, str) else ""
    store.record_prompt(session_id=session_id, cwd=cwd, prompt=prompt_text)
    project_key = project_identity(cwd)
    rows = store.relevant_memories(
        project_key=project_key,
        prompt=prompt_text,
        limit=8,
    )
    context_parts = [format_memory_context(rows, profile=store.profile)]
    context_parts.append(reviewer_context_for_task(prompt_text, profile=store.profile))
    _emit_hook_context(
        "UserPromptSubmit", "\n".join(part for part in context_parts if part)
    )


def handle_agent_pre(payload: dict[str, Any], store: LearningStore) -> None:
    """Claude adapter: attach reviewer context to a native Agent prompt."""

    if payload.get("tool_name") != "Agent":
        _emit_empty_hook_result()
        return
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        _emit_empty_hook_result()
        return
    try:
        updated = augment_agent_input(tool_input, profile=store.profile)
    except OSError, ValueError:
        updated = None
    if updated is None:
        _emit_empty_hook_result()
        return
    _emit_updated_input(updated)


def handle_agent_post(payload: dict[str, Any], store: LearningStore) -> None:
    """Claude adapter: normalize Agent completion before reviewer learning."""

    event = claude_agent_posttool_event(payload)
    if event is None:
        _emit_empty_hook_result()
        return
    result = process_worker_event(event, profile=store.profile)
    if result is None:
        _emit_empty_hook_result()
        return
    _emit_hook_context("PostToolUse", result.parent_context())


def handle_subagent_start(payload: dict[str, Any], store: LearningStore) -> None:
    """Keep a small fallback X1 contract for directly spawned subagent events."""

    _emit_hook_context(
        "SubagentStart",
        reviewer_context_for_task(payload, profile=store.profile),
    )


def handle_subagent_stop(payload: dict[str, Any], store: LearningStore) -> None:
    """Claude adapter: normalize background completion before reviewer learning."""

    event = claude_subagent_stop_event(payload)
    if event is not None:
        process_background_worker_stop(event, profile=store.profile)
    _emit_empty_hook_result()


def run_hook(event: str, *, profile: str | None = None) -> None:
    """Run one lightweight hook event from Claude Code JSON stdin."""

    if not learning_enabled():
        return
    payload = _read_hook_input()
    store = LearningStore(profile=profile)
    if event == "session-start":
        handle_session_start(payload, store)
    elif event == "user-prompt":
        handle_user_prompt(payload, store)
    elif event == "agent-pre":
        handle_agent_pre(payload, store)
    elif event == "agent-post":
        handle_agent_post(payload, store)
    elif event == "subagent-start":
        handle_subagent_start(payload, store)
    elif event == "subagent-stop":
        handle_subagent_stop(payload, store)
    else:
        raise ValueError(f"unknown FCC Learning hook: {event}")
