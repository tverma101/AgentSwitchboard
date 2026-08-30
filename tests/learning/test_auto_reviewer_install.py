"""Installation contract for the thin FCC project-memory hook boundary."""

import json
from pathlib import Path

from free_claude_code.learning.hooks import install_hooks, uninstall_hooks


def _commands(payload: dict[str, object], event: str) -> list[str]:
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get(event)
    if not isinstance(groups, list):
        return []
    commands: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        candidates = group.get("hooks")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if isinstance(candidate, dict) and isinstance(candidate.get("command"), str):
                commands.append(candidate["command"])
    return commands


def test_install_removes_legacy_agent_interception_and_preserves_user_hooks(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Agent",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/usr/bin/python -m free_claude_code.learning.cli "
                                        "hook agent-pre"
                                    ),
                                },
                                {"type": "command", "command": "printf user-agent-hook"},
                            ],
                        }
                    ],
                    "PostToolUse": [
                        {
                            "matcher": "Agent",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/usr/bin/python -m free_claude_code.learning.cli "
                                        "hook agent-post"
                                    ),
                                }
                            ],
                        }
                    ],
                    "SubagentStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/usr/bin/python -m free_claude_code.learning.cli "
                                        "hook subagent-start"
                                    ),
                                }
                            ]
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/usr/bin/python -m free_claude_code.learning.stop_hook"
                                    ),
                                }
                            ]
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    assert install_hooks(tmp_path)
    payload = json.loads(settings.read_text(encoding="utf-8"))

    assert _commands(payload, "PreToolUse") == ["printf user-agent-hook"]
    assert _commands(payload, "PostToolUse") == []
    assert _commands(payload, "SubagentStart") == []
    assert _commands(payload, "Stop") == []
    assert len(_commands(payload, "SessionStart")) == 1
    assert "hook session-start" in _commands(payload, "SessionStart")[0]

    assert uninstall_hooks(tmp_path)
    restored = json.loads(settings.read_text(encoding="utf-8"))
    assert _commands(restored, "PreToolUse") == ["printf user-agent-hook"]
    assert _commands(restored, "SessionStart") == []
