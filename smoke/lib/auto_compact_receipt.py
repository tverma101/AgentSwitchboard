"""Validation for the minimal Claude automatic-compaction receipt."""

from collections.abc import Mapping, Sequence
from typing import Any

AUTO_COMPACT_RECEIPT_SCHEMA = "fcc.claude-auto-compact.v1"
LIVE_INSTALLED_CLAUDE = "live_installed_claude"
SYNTHETIC_CONTRACT = "synthetic_contract"

_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "arguments",
        "content",
        "image_data",
        "messages",
        "prompt",
        "raw_body",
        "request_body",
        "response_body",
        "text",
        "tool_result",
    }
)


class AutoCompactReceiptError(ValueError):
    """A receipt cannot prove the minimal automatic-compaction gate."""


def evidence_kind(receipt: Mapping[str, Any]) -> str:
    """Return the declared evidence class after checking the receipt envelope."""

    _expect(receipt.get("schema") == AUTO_COMPACT_RECEIPT_SCHEMA, "schema")
    evidence = _mapping(receipt, "evidence")
    kind = evidence.get("kind")
    if kind not in {LIVE_INSTALLED_CLAUDE, SYNTHETIC_CONTRACT}:
        raise AutoCompactReceiptError(
            "evidence.kind must be live_installed_claude or synthetic_contract"
        )
    return kind


def validate_live_auto_compact_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, object]:
    """Validate the smallest receipt that can claim installed-client proof.

    This validator deliberately rejects synthetic and contract-only artifacts.
    The returned summary contains only receipt metadata and is safe for test
    diagnostics.
    """

    _reject_forbidden_keys(receipt)
    if evidence_kind(receipt) != LIVE_INSTALLED_CLAUDE:
        raise AutoCompactReceiptError(
            "synthetic/contract evidence cannot satisfy the live installed-Claude gate"
        )
    evidence = _mapping(receipt, "evidence")
    _expect(evidence.get("status") == "passed", "evidence.status")
    _expect(evidence.get("synthetic") is False, "evidence.synthetic")
    _expect(evidence.get("client_executed") is True, "evidence.client_executed")
    _require_string(evidence, "gateway")

    claude = _mapping(receipt, "claude")
    _require_string(claude, "path")
    _require_string(claude, "version")
    _require_string(claude, "launcher")

    harness = _mapping(receipt, "harness")
    _require_string(harness, "package_version")
    _require_string(harness, "isolated_server")
    commit_sha_recorded = harness.get("commit_sha_recorded")
    _expect(type(commit_sha_recorded) is bool, "harness.commit_sha_recorded")
    if commit_sha_recorded:
        commit_sha = harness.get("commit_sha")
        if not isinstance(commit_sha, str) or not commit_sha.strip():
            raise AutoCompactReceiptError(
                "harness.commit_sha is required when commit_sha_recorded is true"
            )
    else:
        _expect(harness.get("commit_sha") is None, "harness.commit_sha")

    context = _mapping(receipt, "context")
    requested_tokens = _positive_int(context, "requested_tokens")
    effective_tokens = _positive_int(context, "effective_tokens")
    _expect(effective_tokens <= requested_tokens, "context.effective_tokens")
    _expect(context.get("context_dropped") is True, "context.context_dropped")
    _require_string(context, "effective_window_observed_via")

    compaction = _mapping(receipt, "compaction")
    _expect(compaction.get("trigger") == "auto", "compaction.trigger")
    _expect(compaction.get("result") == "success", "compaction.result")
    _expect(
        compaction.get("compact_boundary_observed") is True,
        "compaction.compact_boundary_observed",
    )
    _expect(
        compaction.get("compact_metadata_observed") is True,
        "compaction.compact_metadata_observed",
    )
    _expect(
        compaction.get("manual_compact_command_sent") is False,
        "compaction.manual_compact_command_sent",
    )

    post_compaction = _mapping(receipt, "post_compaction")
    _require_string(post_compaction, "tool_name")
    _expect(
        _positive_int(post_compaction, "tool_call_count") >= 1,
        "post_compaction.tool_call_count",
    )
    _expect(
        post_compaction.get("tool_result_completed") is True,
        "post_compaction.tool_result_completed",
    )
    _expect(
        post_compaction.get("resume_invocation_returned") == 0,
        "post_compaction.resume_invocation_returned",
    )
    _expect(
        post_compaction.get("continuation_marker_seen") is True,
        "post_compaction.continuation_marker_seen",
    )
    _expect(post_compaction.get("http_errors") == 0, "post_compaction.http_errors")

    routing = _mapping(receipt, "routing")
    for key in (
        "provider_id",
        "provider_model",
        "provider_model_ref",
        "client_wire_api",
        "upstream_protocol",
        "terminal_event",
    ):
        _require_string(routing, key)
    _expect(
        routing.get("terminal_event") == "response.completed", "routing.terminal_event"
    )
    _expect(routing.get("valid_tool_json") is True, "routing.valid_tool_json")

    telemetry = _mapping(receipt, "telemetry")
    _expect(telemetry.get("metadata_only") is True, "telemetry.metadata_only")
    artifacts = _mapping(receipt, "artifacts")
    _require_string(artifacts, "source")
    _expect(
        artifacts.get("retained_content")
        == "metadata-only receipt; sensitive payloads omitted",
        "artifacts.retained_content",
    )

    unverified_boundaries = receipt.get("unverified_boundaries")
    if not isinstance(unverified_boundaries, Sequence) or isinstance(
        unverified_boundaries, str
    ):
        raise AutoCompactReceiptError(
            "unverified_boundaries must be a sequence of explicit boundary names"
        )
    if not all(
        isinstance(item, str) and item.strip() for item in unverified_boundaries
    ):
        raise AutoCompactReceiptError(
            "unverified_boundaries must contain non-empty strings"
        )
    if (
        not commit_sha_recorded
        and "harness_commit_sha_at_capture" not in unverified_boundaries
    ):
        raise AutoCompactReceiptError(
            "missing explicit unverified boundary for the absent Harness commit SHA"
        )

    return {
        "schema": AUTO_COMPACT_RECEIPT_SCHEMA,
        "evidence_kind": LIVE_INSTALLED_CLAUDE,
        "status": "passed",
        "requested_context_tokens": requested_tokens,
        "effective_context_tokens": effective_tokens,
        "unverified_boundaries": tuple(unverified_boundaries),
    }


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        raise AutoCompactReceiptError(f"{key} must be an object")
    return nested


def _require_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise AutoCompactReceiptError(f"{key} must be a non-empty string")
    return item


def _positive_int(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise AutoCompactReceiptError(f"{key} must be a positive integer")
    return item


def _expect(condition: bool, field: str) -> None:
    if not condition:
        raise AutoCompactReceiptError(f"invalid or missing receipt field: {field}")


def _reject_forbidden_keys(value: object, *, path: str = "receipt") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _FORBIDDEN_KEYS:
                raise AutoCompactReceiptError(
                    f"{path} contains content-bearing field: {key}"
                )
            _reject_forbidden_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, path=f"{path}[{index}]")


__all__ = [
    "AUTO_COMPACT_RECEIPT_SCHEMA",
    "AutoCompactReceiptError",
    "evidence_kind",
    "validate_live_auto_compact_receipt",
]
