import json
import sys
from pathlib import Path

from free_claude_code.learning import cli as learning_cli
from free_claude_code.learning.store import LearningStore


def test_memory_evict_cli_is_global_and_preserves_pinned_memory(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    learning_home = tmp_path / "learning"
    monkeypatch.setenv("FCC_LEARNING_HOME", str(learning_home))
    store = LearningStore(learning_home / "learning.db")

    stale_id, _ = store.add_memory(
        scope="global",
        project_key="",
        text="Old low-confidence observation.",
        confidence=0.5,
        source="verified_fact",
    )
    pinned_id, _ = store.add_memory(
        scope="global",
        project_key="",
        text="Explicit user preference.",
        confidence=0.5,
        source="user_explicit",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["fcc-learning", "memory", "evict", "--older-than-days", "0"],
    )
    learning_cli.main()

    assert json.loads(capsys.readouterr().out) == {"evicted": 1}
    assert store.get_memory(stale_id) is None
    assert store.get_memory(pinned_id) is not None
    assert store.memory_history(stale_id)[-1]["action"] == "evict"
