"""Metadata-only compaction continuity receipts and deterministic gates."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any


class CompactionContinuityError(ValueError):
    """A compaction receipt cannot prove the required continuity invariants."""


@dataclass(frozen=True, slots=True)
class CompactionState:
    """Sanitized structural state at one side of a compaction boundary."""

    provider: str
    model: str
    protocol: str
    system_tool_schema_hash: str
    message_shape_hash: str
    tool_call_ids: tuple[str, ...] = ()
    tool_result_ids: tuple[str, ...] = ()
    reasoning_state_type: str | None = None
    reasoning_state_hash: str | None = None
    media_count: int = 0
    media_type_hash: str | None = None
    learning_memory_ids: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()
    committed_tool_ids: tuple[str, ...] = ()
    retry_attempts: int = 1

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "model",
            "protocol",
            "system_tool_schema_hash",
            "message_shape_hash",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.media_count < 0:
            raise ValueError("media_count must be non-negative")
        if self.retry_attempts <= 0:
            raise ValueError("retry_attempts must be positive")

    def as_receipt(self) -> dict[str, Any]:
        """Serialize only hashes, ids, types, counts, and routing metadata."""

        return asdict(self) | {
            "tool_call_ids": list(self.tool_call_ids),
            "tool_result_ids": list(self.tool_result_ids),
            "learning_memory_ids": list(self.learning_memory_ids),
            "skill_ids": list(self.skill_ids),
            "committed_tool_ids": list(self.committed_tool_ids),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CompactionState:
        """Parse a pre-sanitized state and reject content-bearing receipt fields."""

        forbidden = {
            "prompt",
            "messages",
            "content",
            "text",
            "arguments",
            "tool_result",
            "image",
            "image_data",
            "response",
        }
        leaked = sorted(key for key in value if key in forbidden)
        if leaked:
            raise ValueError(
                f"compaction state must be metadata-only; forbidden fields: {leaked}"
            )
        return cls(
            provider=_required_string(value, "provider"),
            model=_required_string(value, "model"),
            protocol=_required_string(value, "protocol"),
            system_tool_schema_hash=_required_string(value, "system_tool_schema_hash"),
            message_shape_hash=_required_string(value, "message_shape_hash"),
            tool_call_ids=_string_tuple(value.get("tool_call_ids"), "tool_call_ids"),
            tool_result_ids=_string_tuple(
                value.get("tool_result_ids"), "tool_result_ids"
            ),
            reasoning_state_type=_optional_string(
                value.get("reasoning_state_type"), "reasoning_state_type"
            ),
            reasoning_state_hash=_optional_string(
                value.get("reasoning_state_hash"), "reasoning_state_hash"
            ),
            media_count=_non_negative_int(value.get("media_count", 0), "media_count"),
            media_type_hash=_optional_string(
                value.get("media_type_hash"), "media_type_hash"
            ),
            learning_memory_ids=_string_tuple(
                value.get("learning_memory_ids"), "learning_memory_ids"
            ),
            skill_ids=_string_tuple(value.get("skill_ids"), "skill_ids"),
            committed_tool_ids=_string_tuple(
                value.get("committed_tool_ids"), "committed_tool_ids"
            ),
            retry_attempts=_positive_int(
                value.get("retry_attempts", 1), "retry_attempts"
            ),
        )


def validate_compaction_continuity(
    before: CompactionState,
    after: CompactionState,
) -> dict[str, Any]:
    """Return a machine-readable continuity gate for one compact boundary."""

    invariants = {
        "routing_preserved": (
            before.provider,
            before.model,
            before.protocol,
        )
        == (
            after.provider,
            after.model,
            after.protocol,
        ),
        "system_tool_schema_preserved": before.system_tool_schema_hash
        == after.system_tool_schema_hash,
        "message_shape_preserved": before.message_shape_hash
        == after.message_shape_hash,
        "tool_call_ids_preserved": before.tool_call_ids == after.tool_call_ids,
        "tool_result_ids_preserved": before.tool_result_ids == after.tool_result_ids,
        "committed_tools_not_replayed": (
            before.committed_tool_ids == after.committed_tool_ids
            and len(before.committed_tool_ids) == len(set(before.committed_tool_ids))
            and len(after.tool_call_ids) == len(set(after.tool_call_ids))
            and len(after.committed_tool_ids) == len(set(after.committed_tool_ids))
            and set(after.committed_tool_ids).issubset(set(after.tool_call_ids))
        ),
        "reasoning_state_preserved": (
            before.reasoning_state_type,
            before.reasoning_state_hash,
        )
        == (
            after.reasoning_state_type,
            after.reasoning_state_hash,
        ),
        "media_preserved": (
            before.media_count,
            before.media_type_hash,
        )
        == (
            after.media_count,
            after.media_type_hash,
        ),
        "learning_memory_not_duplicated": len(after.learning_memory_ids)
        == len(set(after.learning_memory_ids)),
        "skills_not_duplicated": len(after.skill_ids) == len(set(after.skill_ids)),
        "retry_amplification_bounded": after.retry_attempts
        <= before.retry_attempts + 1,
    }
    receipt = {
        "schema": "fcc.compaction-continuity.v1",
        "passed": all(invariants.values()),
        "invariants": invariants,
        "before": before.as_receipt(),
        "after": after.as_receipt(),
    }
    return receipt


def assert_compaction_continuity(
    before: CompactionState,
    after: CompactionState,
) -> dict[str, Any]:
    """Validate a boundary or raise with the failed invariant names."""

    receipt = validate_compaction_continuity(before, after)
    if not receipt["passed"]:
        failed = [name for name, passed in receipt["invariants"].items() if not passed]
        raise CompactionContinuityError(
            "compaction continuity failed: " + ", ".join(failed)
        )
    return receipt


def _required_string(value: Mapping[str, Any], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return result.strip()


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    return value


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueError(f"{name} must be an array of strings")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{name} must be an array of non-empty strings")
    return tuple(value)


def _non_negative_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    result = _non_negative_int(value, name)
    if result == 0:
        raise ValueError(f"{name} must be positive")
    return result
