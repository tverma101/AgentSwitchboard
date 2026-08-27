"""Metadata-only native OpenCode vs Harness behavior comparator.

This module intentionally compares normalized receipts rather than prompts or raw
wire payloads. It is shared evidence machinery for the remaining OpenCode Go,
fault-attribution, and certification issues; it is not another provider/router.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from free_claude_code.core.fault_attribution import FaultConfidence, FaultDomain

COMPARATOR_SCHEMA = "fcc.native-harness-comparator.v1"

_FORBIDDEN_RECEIPT_KEYS = frozenset(
    {
        "arguments",
        "content",
        "data",
        "image",
        "image_data",
        "input",
        "messages",
        "output",
        "prompt",
        "reasoning",
        "response",
        "session_id",
        "text",
        "tool_arguments",
        "tool_result",
    }
)

_CONFIDENCE_RANK = {
    FaultConfidence.LOW.value: 0,
    FaultConfidence.MEDIUM.value: 1,
    FaultConfidence.HIGH.value: 2,
}


@dataclass(frozen=True, slots=True)
class PathObservation:
    """One sanitized observation of the same logical scenario on one path."""

    scenario_id: str
    path: Literal["native", "harness"]
    success: bool
    protocol: str
    upstream_attempts: int
    event_sequence: tuple[str, ...] = ()
    terminal_event: str | None = None
    tool_call_count: int = 0
    complete_tool_calls: bool | None = None
    valid_tool_json: bool | None = None
    stable_prefix_hash: str | None = None
    request_shape_hash: str | None = None
    cache_read_tokens: int | None = None
    input_tokens: int | None = None
    ttft_ms: float | None = None
    duration_ms: float | None = None
    fault_domain: str = FaultDomain.UNKNOWN.value
    confidence: str = FaultConfidence.LOW.value
    evidence_codes: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PathObservation:
        """Validate a content-free observation mapping."""

        _reject_content_bearing_fields(value)
        scenario_id = _required_string(value, "scenario_id")
        path = _required_string(value, "path")
        if path not in {"native", "harness"}:
            raise ValueError("path must be 'native' or 'harness'")
        success = value.get("success")
        if not isinstance(success, bool):
            raise ValueError("success must be a boolean")
        protocol = _required_string(value, "protocol")
        if protocol not in {"responses", "messages", "chat_completions"}:
            raise ValueError("protocol must be a supported protocol string")
        upstream_attempts = value.get("upstream_attempts", 1)
        if (
            not isinstance(upstream_attempts, int)
            or isinstance(upstream_attempts, bool)
            or upstream_attempts <= 0
        ):
            raise ValueError("upstream_attempts must be a positive integer")

        event_sequence_raw = value.get("event_sequence", value.get("event_types", ()))
        if not isinstance(event_sequence_raw, list | tuple) or not all(
            isinstance(item, str) and item for item in event_sequence_raw
        ):
            raise ValueError("event_sequence must contain non-empty strings")
        if len(event_sequence_raw) > 4_096:
            raise ValueError("event_sequence exceeds the bounded receipt limit")

        fault_domain = value.get("fault_domain", FaultDomain.UNKNOWN.value)
        if fault_domain not in {domain.value for domain in FaultDomain}:
            raise ValueError("fault_domain is not recognized")
        confidence = value.get("confidence", FaultConfidence.LOW.value)
        if confidence not in _CONFIDENCE_RANK:
            raise ValueError("confidence is not recognized")

        evidence_codes_raw = value.get("evidence_codes", ())
        if not isinstance(evidence_codes_raw, list | tuple) or not all(
            isinstance(item, str) and item for item in evidence_codes_raw
        ):
            raise ValueError("evidence_codes must contain non-empty strings")
        if len(evidence_codes_raw) > 256:
            raise ValueError("evidence_codes exceeds the bounded receipt limit")

        return cls(
            scenario_id=scenario_id,
            path=path,  # type: ignore[arg-type]
            success=success,
            protocol=protocol,
            upstream_attempts=upstream_attempts,
            event_sequence=tuple(event_sequence_raw),
            terminal_event=_optional_string(value, "terminal_event"),
            tool_call_count=_non_negative_int(value, "tool_call_count", default=0),
            complete_tool_calls=_optional_bool(value, "complete_tool_calls"),
            valid_tool_json=_optional_bool(value, "valid_tool_json"),
            stable_prefix_hash=_optional_string(value, "stable_prefix_hash"),
            request_shape_hash=_optional_string(value, "request_shape_hash"),
            cache_read_tokens=_optional_non_negative_int(value, "cache_read_tokens"),
            input_tokens=_optional_non_negative_int(value, "input_tokens"),
            ttft_ms=_optional_non_negative_number(value, "ttft_ms"),
            duration_ms=_optional_non_negative_number(value, "duration_ms"),
            fault_domain=fault_domain,
            confidence=confidence,
            evidence_codes=tuple(evidence_codes_raw),
        )


def compare_paths(
    native: PathObservation,
    harness: PathObservation,
) -> dict[str, Any]:
    """Compare the same scenario and return a bounded attribution receipt."""

    if native.path != "native" or harness.path != "harness":
        raise ValueError("compare_paths requires native then harness observations")
    if native.scenario_id != harness.scenario_id:
        raise ValueError("observations must describe the same scenario_id")

    protocol_match = native.protocol == harness.protocol
    request_shape_match = _optional_match(
        native.request_shape_hash, harness.request_shape_hash
    )
    stable_prefix_match = _optional_match(
        native.stable_prefix_hash, harness.stable_prefix_hash
    )
    event_sequence_match = native.event_sequence == harness.event_sequence
    terminal_match = native.terminal_event == harness.terminal_event
    tool_structure_match = (
        native.tool_call_count == harness.tool_call_count
        and native.complete_tool_calls == harness.complete_tool_calls
        and native.valid_tool_json == harness.valid_tool_json
    )

    domain, confidence, evidence_codes = _attribute(
        native,
        harness,
        protocol_match=protocol_match,
        request_shape_match=request_shape_match,
        stable_prefix_match=stable_prefix_match,
        event_sequence_match=event_sequence_match,
        terminal_match=terminal_match,
    )

    return {
        "schema": COMPARATOR_SCHEMA,
        "scenario_id": native.scenario_id,
        "native": _observation_receipt(native),
        "harness": _observation_receipt(harness),
        "comparison": {
            "success_match": native.success == harness.success,
            "protocol_match": protocol_match,
            "request_shape_match": request_shape_match,
            "stable_prefix_match": stable_prefix_match,
            "event_sequence_match": event_sequence_match,
            "terminal_match": terminal_match,
            "tool_structure_match": tool_structure_match,
            "attempt_delta": harness.upstream_attempts - native.upstream_attempts,
            "cache_read_delta": _optional_delta(
                native.cache_read_tokens, harness.cache_read_tokens
            ),
            "input_token_delta": _optional_delta(
                native.input_tokens, harness.input_tokens
            ),
            "ttft_delta_ms": _optional_delta(native.ttft_ms, harness.ttft_ms),
            "duration_delta_ms": _optional_delta(
                native.duration_ms, harness.duration_ms
            ),
        },
        "attribution": {
            "fault_domain": domain,
            "confidence": confidence,
            "evidence_codes": evidence_codes,
        },
    }


def load_observation(path: str | Path) -> PathObservation:
    """Load one normalized JSON observation from disk."""

    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("observation file must contain one JSON object")
    return PathObservation.from_mapping(value)


def write_comparison(receipt: dict[str, Any], path: str | Path) -> None:
    """Persist one metadata-only comparator receipt."""

    _reject_content_bearing_fields(receipt)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _attribute(
    native: PathObservation,
    harness: PathObservation,
    *,
    protocol_match: bool,
    request_shape_match: bool | None,
    stable_prefix_match: bool | None,
    event_sequence_match: bool,
    terminal_match: bool,
) -> tuple[str | None, str, list[str]]:
    if not protocol_match:
        return (
            FaultDomain.HARNESS_BRIDGE.value,
            FaultConfidence.HIGH.value,
            ["native_harness_protocol_mismatch"],
        )

    if native.success and harness.success:
        return None, FaultConfidence.HIGH.value, ["both_paths_succeeded"]

    if native.success and not harness.success:
        if harness.fault_domain != FaultDomain.UNKNOWN.value:
            return (
                harness.fault_domain,
                harness.confidence,
                ["native_succeeded_harness_failed", *harness.evidence_codes],
            )
        if request_shape_match is False:
            return (
                FaultDomain.HARNESS_BRIDGE.value,
                FaultConfidence.HIGH.value,
                ["native_succeeded_harness_failed", "request_shape_mismatch"],
            )
        if stable_prefix_match is False:
            return (
                FaultDomain.HARNESS_BRIDGE.value,
                FaultConfidence.MEDIUM.value,
                ["native_succeeded_harness_failed", "stable_prefix_mismatch"],
            )
        return (
            FaultDomain.UNKNOWN.value,
            FaultConfidence.LOW.value,
            ["native_succeeded_harness_failed", "insufficient_ownership_evidence"],
        )

    if not native.success and not harness.success:
        if (
            native.fault_domain == harness.fault_domain
            and native.fault_domain != FaultDomain.UNKNOWN.value
        ):
            return (
                native.fault_domain,
                _lower_confidence(native.confidence, harness.confidence),
                [
                    "both_paths_same_fault_domain",
                    *native.evidence_codes,
                    *harness.evidence_codes,
                ],
            )
        if event_sequence_match and terminal_match:
            return (
                FaultDomain.UNKNOWN.value,
                FaultConfidence.MEDIUM.value,
                ["both_paths_failed_with_matching_stream_shape"],
            )
        return (
            FaultDomain.UNKNOWN.value,
            FaultConfidence.LOW.value,
            ["both_paths_failed_differently", "insufficient_ownership_evidence"],
        )

    return (
        FaultDomain.UNKNOWN.value,
        FaultConfidence.LOW.value,
        ["native_failed_harness_succeeded", "do_not_blame_harness_from_single_run"],
    )


def _observation_receipt(value: PathObservation) -> dict[str, Any]:
    receipt = asdict(value)
    receipt["event_sequence"] = list(value.event_sequence)
    receipt["evidence_codes"] = list(value.evidence_codes)
    return receipt


def _reject_content_bearing_fields(value: object) -> None:
    if isinstance(value, dict):
        forbidden = sorted(
            key for key in value if isinstance(key, str) and key in _FORBIDDEN_RECEIPT_KEYS
        )
        if forbidden:
            raise ValueError(
                "comparator receipts must not contain content-bearing fields: "
                + ", ".join(forbidden)
            )
        for child in value.values():
            _reject_content_bearing_fields(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _reject_content_bearing_fields(child)


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{key} must be a non-empty string")
    return raw


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{key} must be a non-empty string when present")
    return raw


def _optional_bool(value: dict[str, Any], key: str) -> bool | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, bool):
        raise ValueError(f"{key} must be a boolean when present")
    return raw


def _non_negative_int(value: dict[str, Any], key: str, *, default: int) -> int:
    raw = value.get(key, default)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return raw


def _optional_non_negative_int(value: dict[str, Any], key: str) -> int | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ValueError(f"{key} must be a non-negative integer when present")
    return raw


def _optional_non_negative_number(value: dict[str, Any], key: str) -> float | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, int | float) or isinstance(raw, bool) or raw < 0:
        raise ValueError(f"{key} must be a non-negative number when present")
    return float(raw)


def _optional_match(left: str | None, right: str | None) -> bool | None:
    if left is None or right is None:
        return None
    return left == right


def _optional_delta(
    native: int | float | None, harness: int | float | None
) -> int | float | None:
    if native is None or harness is None:
        return None
    return harness - native


def _lower_confidence(left: str, right: str) -> str:
    return min((left, right), key=_CONFIDENCE_RANK.__getitem__)
