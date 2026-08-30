"""Hard-budget formatting for FCC's injected learned-memory slice."""

from collections.abc import Iterable
from typing import Any

from .store import format_memory_context

# Keep ordinary learned-memory injection small even when the persistent store grows.
# This is a byte ceiling, not a claim about exact tokenizer behavior. The broader
# Learning v2 work can add measured token accounting without weakening this bound.
MAX_MEMORY_CONTEXT_BYTES = 6_144


def bounded_memory_context(
    rows: Iterable[Any],
    *,
    profile: str = "default",
    max_bytes: int = MAX_MEMORY_CONTEXT_BYTES,
) -> str:
    """Format the highest-ranked memories that fit inside one hard byte budget.

    ``rows`` is already ordered by ``LearningStore.relevant_memories``. Oversized
    records are skipped rather than allowing one verbose memory to consume the
    entire hot-memory slice. Relative order among accepted records is preserved.
    """

    budget = max(0, int(max_bytes))
    if budget == 0:
        return ""

    selected: list[Any] = []
    context = ""
    for row in rows:
        candidate_rows = [*selected, row]
        candidate = format_memory_context(candidate_rows, profile=profile)
        if len(candidate.encode("utf-8")) > budget:
            continue
        selected.append(row)
        context = candidate
    return context
