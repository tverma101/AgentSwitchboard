import sqlite3
import time
from pathlib import Path

from free_claude_code.learning.memory_context import select_bounded_memory_context
from free_claude_code.learning.store import LearningStore


def _store(tmp_path: Path) -> LearningStore:
    return LearningStore(path=tmp_path / "learning.sqlite3", profile="coding")


def _age_memory(
    store: LearningStore,
    memory_id: int,
    *,
    updated_at: float,
    last_used_at: float | None,
) -> None:
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE memories SET updated_at = ?, last_used_at = ? WHERE id = ?",
            (updated_at, last_used_at, memory_id),
        )


def test_ranking_does_not_credit_memory_until_injected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memory_id, inserted = store.add_memory(
        scope="project",
        project_key="repo",
        text="check registration before reinstalling",
        confidence=0.8,
        source="verified_failure",
    )
    assert inserted is True

    ranked = store.relevant_memories(project_key="repo", prompt="registration", limit=8)

    assert [int(row["id"]) for row in ranked] == [memory_id]
    before = store.get_memory(memory_id, project_key="repo")
    assert before is not None
    assert int(before["use_count"]) == 0
    assert before["last_used_at"] is None

    assert store.mark_memories_used((memory_id,)) == 1
    after = store.get_memory(memory_id, project_key="repo")
    assert after is not None
    assert int(after["use_count"]) == 1
    assert after["last_used_at"] is not None


def test_budget_skipped_memory_gets_no_usage_credit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    oversized_id, _ = store.add_memory(
        scope="project",
        project_key="repo",
        text="oversized " + "x" * 4_000,
        confidence=1.0,
        source="verified_failure",
    )
    compact_id, _ = store.add_memory(
        scope="project",
        project_key="repo",
        text="compact verified cave",
        confidence=0.8,
        source="verified_failure",
    )

    ranked = store.relevant_memories(project_key="repo", limit=8)
    selection = select_bounded_memory_context(ranked, max_bytes=700)
    store.mark_memories_used(selection.memory_ids)

    assert compact_id in selection.memory_ids
    assert oversized_id not in selection.memory_ids
    oversized = store.get_memory(oversized_id, project_key="repo")
    compact = store.get_memory(compact_id, project_key="repo")
    assert oversized is not None
    assert compact is not None
    assert int(oversized["use_count"]) == 0
    assert oversized["last_used_at"] is None
    assert int(compact["use_count"]) == 1
    assert compact["last_used_at"] is not None


def test_previously_used_memory_can_age_out_when_use_is_stale(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memory_id, _ = store.add_memory(
        scope="project",
        project_key="repo",
        text="old low confidence cave",
        confidence=0.5,
        source="verified_failure",
    )
    store.mark_memories_used((memory_id,))
    old = time.time() - 365 * 86400
    _age_memory(store, memory_id, updated_at=old, last_used_at=old)

    assert store.evict_stale_memories(older_than_days=180) == 1
    assert store.get_memory(memory_id, project_key="repo") is None


def test_recent_use_protects_old_low_confidence_memory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memory_id, _ = store.add_memory(
        scope="project",
        project_key="repo",
        text="currently useful old cave",
        confidence=0.5,
        source="verified_failure",
    )
    old = time.time() - 365 * 86400
    _age_memory(store, memory_id, updated_at=old, last_used_at=None)
    store.mark_memories_used((memory_id,))

    assert store.evict_stale_memories(older_than_days=180) == 0
    assert store.get_memory(memory_id, project_key="repo") is not None


def test_pinned_explicit_memory_survives_stale_retention(tmp_path: Path) -> None:
    store = _store(tmp_path)
    memory_id, _ = store.add_memory(
        scope="project",
        project_key="repo",
        text="user explicit invariant",
        confidence=0.4,
        source="user_explicit",
    )
    old = time.time() - 365 * 86400
    _age_memory(store, memory_id, updated_at=old, last_used_at=old)

    assert store.evict_stale_memories(older_than_days=180) == 0
    assert store.get_memory(memory_id, project_key="repo") is not None
