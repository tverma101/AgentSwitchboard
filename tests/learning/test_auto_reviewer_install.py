"""Installation contract for automatic Agent reviewer hooks."""

import json
from pathlib import Path

from free_claude_code.learning.hooks import install_hooks, uninstall_hooks


def test_agent_hooks_install_with_exact_matchers_and_uninstall_cleanly(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")

    assert install_hooks(tmp_path)
    payload = json.loads(settings.read_text(encoding="utf-8"))

    for event, hook_name in (("PreToolUse", "agent-pre"), ("PostToolUse", "agent-post")):
        groups = payload["hooks"][event]
        matching = [group for group in groups if group.get("matcher") == "Agent"]
        assert len(matching) == 1
        commands = [hook["command"] for hook in matching[0]["hooks"]]
        assert len(commands) == 1
        assert f"hook {hook_name}" in commands[0]

    assert uninstall_hooks(tmp_path)
    restored = json.loads(settings.read_text(encoding="utf-8"))
    assert "PreToolUse" not in restored.get("hooks", {})
    assert "PostToolUse" not in restored.get("hooks", {})
