"""Sanitized, protocol-neutral fault attribution and receipt helpers."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class FaultDomain(StrEnum):
    """Owners used for end-to-end failure attribution."""

    CLAUDE_CLIENT = "claude_client"
    HARNESS_INGRESS = "harness_ingress"
    HARNESS_BRIDGE = "harness_bridge"
    HARNESS_TRANSPORT = "harness_transport"
    OPENCODE_GATEWAY = "opencode_gateway"
    MODEL_OUTPUT = "model_output"
    TOOL_EXECUTOR = "tool_executor"
    UPSTREAM_CACHE = "upstream_cache"
    UNKNOWN = "unknown"


class FaultConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_MAX_EVENT_TYPES = 4_096


def canonical_hash(value: Any) -> str:
    """Return a deterministic content hash without retaining the content."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_prefix_hash(body: dict[str, Any]) -> str:
    """Hash the cacheable request prefix while excluding the conversation suffix."""

    prefix = {
        key: body[key]
        for key in (
            "model",
            "instructions",
            "system",
            "tools",
            "tool_choice",
            "metadata",
        )
        if key in body
    }
    input_items = body.get("input")
    if isinstance(input_items, list):
        prefix["input_prefix"] = input_items[:-1] if input_items else []
    else:
        messages = body.get("messages")
        if isinstance(messages, list):
            prefix["messages_prefix"] = messages[:-1] if messages else []
    return canonical_hash(prefix)


@dataclass(slots=True)
class AttemptEvidence:
    """Metadata-only receipt for one upstream attempt."""

    turn_id: str
    request_id: str | None
    protocol: str
    provider: str
    model: str
    attempt_number: int
    fault_domain: FaultDomain = FaultDomain.UNKNOWN
    confidence: FaultConfidence = FaultConfidence.LOW
    evidence_codes: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    terminal_event: str | None = None
    upstream_response_id: str | None = None
    http_status: int | None = None
    bytes_received: int = 0
    tool_call_count: int = 0
    complete_tool_calls: bool | None = None
    valid_tool_json: bool | None = None
    output_committed: bool = False
    tool_executed: bool = False
    retry_reason: str | None = None
    input_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    output_tokens: int | None = None
    requested_reasoning_effort: str | None = None
    requested_reasoning_budget_tokens: int | None = None
    effective_reasoning_effort: str | None = None
    provider_reasoning_tokens: int | None = None
    provider_reasoning_item: bool = False
    provider_visible_reasoning_summary: bool = False
    provider_reasoning_text: bool = False
    provider_opaque_reasoning: bool = False
    opaque_reasoning_hash: str | None = None
    harness_thinking_block: bool = False
    harness_thinking_delta: bool = False
    stable_prefix_hash: str | None = None
    request_shape_hash: str | None = None
    tool_schema_hash: str | None = None

    def add_event(self, event_type: str, *, byte_count: int = 0) -> None:
        if len(self.event_types) < _MAX_EVENT_TYPES:
            if len(self.event_types) == _MAX_EVENT_TYPES - 1:
                self.event_types.append("event_sequence_truncated")
            else:
                self.event_types.append(event_type)
        self.bytes_received += max(0, byte_count)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "fault_domain": self.fault_domain.value,
            "confidence": self.confidence.value,
        }


def classify_failure(
    *,
    error_code: str | None = None,
    transport: bool = False,
    bridge: bool = False,
    output_committed: bool = False,
    complete_tool_call: bool = False,
    invalid_tool_json: bool = False,
    missing_terminal: bool = False,
) -> tuple[FaultDomain, FaultConfidence, list[str]]:
    """Apply deterministic ownership rules to sanitized stream evidence."""

    def codes_with_output(codes: list[str]) -> list[str]:
        if output_committed:
            codes.append("downstream_output_already_committed")
        return codes

    if bridge:
        return (
            FaultDomain.HARNESS_BRIDGE,
            FaultConfidence.HIGH,
            codes_with_output(["bridge_conversion_error"]),
        )
    if invalid_tool_json:
        return (
            FaultDomain.MODEL_OUTPUT,
            FaultConfidence.MEDIUM,
            codes_with_output(["complete_event_invalid_tool_json"]),
        )
    if missing_terminal and complete_tool_call:
        return (
            FaultDomain.OPENCODE_GATEWAY,
            FaultConfidence.HIGH,
            codes_with_output(["complete_tool_call_missing_terminal"]),
        )
    if missing_terminal:
        return (
            FaultDomain.OPENCODE_GATEWAY,
            FaultConfidence.MEDIUM,
            codes_with_output(["stream_closed_without_terminal"]),
        )
    if transport:
        domain = FaultDomain.HARNESS_TRANSPORT
        confidence = FaultConfidence.MEDIUM
        codes = ["transport_failure"]
    elif error_code:
        domain = FaultDomain.OPENCODE_GATEWAY
        confidence = FaultConfidence.HIGH
        codes = [f"upstream_error:{error_code}"]
    else:
        domain = FaultDomain.UNKNOWN
        confidence = FaultConfidence.LOW
        codes = ["insufficient_evidence"]
    return domain, confidence, codes_with_output(codes)
