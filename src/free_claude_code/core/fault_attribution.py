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
_REQUEST_METADATA_KEYS = frozenset({"metadata", "prompt_cache_key"})


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


def request_shape_hash(body: dict[str, Any]) -> str:
    """Hash logical request shape without cache/session metadata.

    ``prompt_cache_key`` partitions provider cache state but is not part of the
    prompt or request shape.  Arbitrary ``metadata`` is likewise excluded so
    request correlation, timestamps, and other client bookkeeping cannot make
    comparable native/Harness receipts look like different envelopes.
    """

    shape = {
        key: value for key, value in body.items() if key not in _REQUEST_METADATA_KEYS
    }
    return canonical_hash(shape)


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


def media_metadata(value: Any) -> tuple[int, str | None]:
    """Return count and ordered type hash without retaining media payloads."""
    descriptors: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            block_type = item.get("type")
            if block_type in {"image", "document"}:
                source = item.get("source")
                media_type = (
                    source.get("media_type") if isinstance(source, dict) else None
                )
                descriptors.append(
                    f"{block_type}:{media_type if isinstance(media_type, str) else 'unknown'}"
                )
            for child in item.values():
                visit(child)
        elif isinstance(item, list | tuple):
            for child in item:
                visit(child)

    visit(value)
    return len(descriptors), canonical_hash(descriptors) if descriptors else None


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
    media_count: int = 0
    media_type_hash: str | None = None
    duration_ms: int | None = None
    time_to_first_token_ms: int | None = None
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
    requested_reasoning_control: str | None = None
    requested_reasoning_effort: str | None = None
    requested_reasoning_budget_tokens: int | None = None
    effective_reasoning_effort: str | None = None
    provider_reasoning_tokens: int | None = None
    provider_reasoning_item: bool = False
    provider_visible_reasoning_summary: bool = False
    provider_visible_reasoning_summary_length: int | None = None
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
    harness_transport: bool = False,
    bridge: bool = False,
    output_committed: bool = False,
    complete_tool_call: bool = False,
    invalid_tool_json: bool = False,
    missing_terminal: bool = False,
) -> tuple[FaultDomain, FaultConfidence, list[str]]:
    """Apply deterministic ownership rules to sanitized stream evidence.

    A generic transport signal proves only that the request failed around the
    network boundary; it does not prove whether FCC, DNS/TLS, the network, or
    the upstream edge owned the failure. ``harness_transport`` is reserved for
    failures whose local Harness ownership was established independently.
    """

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
    if harness_transport:
        domain = FaultDomain.HARNESS_TRANSPORT
        confidence = FaultConfidence.HIGH
        codes = ["local_transport_failure_proven"]
    elif error_code:
        domain = FaultDomain.OPENCODE_GATEWAY
        confidence = FaultConfidence.HIGH
        codes = [f"upstream_error:{error_code}"]
    elif transport:
        domain = FaultDomain.UNKNOWN
        confidence = FaultConfidence.MEDIUM
        codes = ["transport_failure_ownership_unproven"]
    else:
        domain = FaultDomain.UNKNOWN
        confidence = FaultConfidence.LOW
        codes = ["insufficient_evidence"]
    return domain, confidence, codes_with_output(codes)
