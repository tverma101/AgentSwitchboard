"""Tests for the hard-budget FCC learned-memory context slice."""

from free_claude_code.learning.memory_context import (
    MAX_MEMORY_CONTEXT_BYTES,
    bounded_memory_context,
)


def _memory(
    memory_id: int, text: str, *, scope: str = "project"
) -> dict[str, object]:
    return {"id": memory_id, "scope": scope, "text": text}


def test_bounded_memory_context_never_exceeds_requested_bytes() -> None:
    rows = [_memory(index, f"rule-{index} " + "x" * 300) for index in range(40)]

    context = bounded_memory_context(rows, profile="coding", max_bytes=1_200)

    assert context
    assert len(context.encode("utf-8")) <= 1_200
    assert "profile: coding" in context


def test_bounded_memory_context_skips_one_oversized_record() -> None:
    rows = [
        _memory(1, "x" * 4_000),
        _memory(2, "small verified project cave"),
    ]

    context = bounded_memory_context(rows, max_bytes=700)

    assert "memory:1" not in context
    assert "memory:2" in context
    assert "small verified project cave" in context


def test_bounded_memory_context_preserves_rank_order_for_records_that_fit() -> None:
    rows = [
        _memory(7, "highest ranked"),
        _memory(3, "second ranked"),
        _memory(9, "third ranked"),
    ]

    context = bounded_memory_context(rows, max_bytes=2_000)

    assert context.index("memory:7") < context.index("memory:3")
    assert context.index("memory:3") < context.index("memory:9")


def test_bounded_memory_context_zero_budget_injects_nothing() -> None:
    assert bounded_memory_context([_memory(1, "keep me")], max_bytes=0) == ""


def test_default_hot_memory_slice_has_a_fixed_ceiling() -> None:
    rows = [_memory(index, "compact pointer " + "z" * 120) for index in range(200)]

    context = bounded_memory_context(rows)

    assert len(context.encode("utf-8")) <= MAX_MEMORY_CONTEXT_BYTES
