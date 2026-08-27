"""OpenCode Go token-cost and cache-efficiency receipt helpers.

Pricing is intentionally source-stamped instead of fetched at benchmark time so a
receipt remains reproducible after OpenCode changes prices.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

PRICING_SOURCE_DATE = "2026-08-23"
PRICING_SOURCE_URL = "https://dev.opencode.ai/docs/go/"
COMPACTION_PHASES = frozenset(
    {
        "pre_compact",
        "compact_turn",
        "post_compact",
        "mature_post_compact",
        "resume",
    }
)
COMPACTION_ECONOMICS_SCHEMA = "fcc.compaction-economics.v1"
COMPACTION_ECONOMICS_PHASE_SEQUENCE = (
    "pre_compact",
    "compact_turn",
    "post_compact",
    "mature_post_compact",
    "resume",
)
_RAW_RECEIPT_FIELDS = frozenset(
    {
        "prompt",
        "messages",
        "content",
        "text",
        "input",
        "response",
        "output",
        "tool_result",
        "arguments",
        "image",
        "image_data",
        "reasoning",
    }
)


COMPACTION_ECONOMICS_RECEIPT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "FCC synthetic compaction economics receipt",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "evidence", "model", "protocol", "turns"],
    "properties": {
        "schema": {"const": COMPACTION_ECONOMICS_SCHEMA},
        "evidence": {"const": "synthetic-only"},
        "fixture": {"type": "string", "minLength": 1},
        "model": {"type": "string", "minLength": 1},
        "protocol": {
            "type": "string",
            "enum": ["responses", "messages", "chat_completions"],
        },
        "turns": {
            "type": "array",
            "minItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "model",
                    "protocol",
                    "logical_request_id",
                    "phase",
                    "input_tokens",
                    "effective_uncached_input_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                    "output_tokens",
                    "upstream_attempts",
                    "retries",
                    "stable_prefix_hash",
                    "request_shape_hash",
                    "compact_boundary_hash",
                    "learning_memory_ids",
                ],
                "properties": {
                    "model": {"type": "string", "minLength": 1},
                    "protocol": {"type": "string", "minLength": 1},
                    "logical_request_id": {"type": "string", "minLength": 1},
                    "phase": {
                        "type": "string",
                        "enum": list(COMPACTION_ECONOMICS_PHASE_SEQUENCE),
                    },
                    "input_tokens": {"type": "integer", "minimum": 0},
                    "effective_uncached_input_tokens": {
                        "type": "integer",
                        "minimum": 0,
                    },
                    "cache_read_tokens": {"type": "integer", "minimum": 0},
                    "cache_write_tokens": {"type": "integer", "minimum": 0},
                    "output_tokens": {"type": "integer", "minimum": 0},
                    "upstream_attempts": {"type": "integer", "minimum": 1},
                    "retries": {"type": "integer", "minimum": 0},
                    "retry_reason": {"type": "string"},
                    "stable_prefix_hash": {"type": "string", "minLength": 1},
                    "request_shape_hash": {"type": "string", "minLength": 1},
                    "compact_boundary_hash": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "learning_memory_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "ttft_ms": {"type": "number", "minimum": 0},
                    "duration_ms": {"type": "number", "minimum": 0},
                },
            },
        },
    },
}


@dataclass(frozen=True, slots=True)
class GoPrice:
    """USD per one million tokens for disjoint usage buckets."""

    input: float
    output: float
    cache_read: float
    cache_write: float = 0.0


@dataclass(frozen=True, slots=True)
class GoUsage:
    """One logical request's disjoint billing-token buckets."""

    model: str
    uncached_input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    context_tokens: int | None = None
    price_variant: str | None = None
    protocol: str | None = None
    logical_request_id: str | None = None
    upstream_attempts: int = 1
    retry_reason: str | None = None
    stable_prefix_hash: str | None = None
    request_shape_hash: str | None = None
    tool_schema_hash: str | None = None
    ttft_ms: float | None = None
    duration_ms: float | None = None
    bytes_in: int | None = None
    bytes_out: int | None = None
    phase: str | None = None
    compact_boundary_hash: str | None = None
    reasoning_tokens: int | None = None
    learning_memory_ids: tuple[str, ...] = ()

    @property
    def input_tokens(self) -> int:
        """Return total input tokens represented by the disjoint input buckets."""

        return self.uncached_input_tokens + self.cache_read_tokens

    @property
    def effective_uncached_input_tokens(self) -> int:
        """Return input tokens billed outside the provider cache-read bucket."""

        return self.uncached_input_tokens

    @property
    def attempts(self) -> int:
        """Return upstream attempts for this logical request."""

        return self.upstream_attempts

    @property
    def retries(self) -> int:
        """Return retries after the first upstream attempt."""

        return self.upstream_attempts - 1

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> GoUsage:
        leaked = sorted(_RAW_RECEIPT_FIELDS.intersection(value))
        if leaked:
            raise ValueError(
                f"receipt must be metadata-only; forbidden fields: {leaked}"
            )
        required = (
            "model",
            "cache_read_tokens",
            "cache_write_tokens",
            "output_tokens",
        )
        missing = [key for key in required if key not in value]
        if (
            "uncached_input_tokens" not in value
            and "effective_uncached_input_tokens" not in value
        ):
            missing.append("effective_uncached_input_tokens")
        if missing:
            raise ValueError(f"receipt row missing fields: {missing}")
        model = value["model"]
        if not isinstance(model, str) or not model:
            raise ValueError("receipt model must be a non-empty string")
        counts: dict[str, int] = {}
        for key in ("cache_read_tokens", "cache_write_tokens", "output_tokens"):
            raw = value[key]
            if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
                raise ValueError(f"{key} must be a non-negative integer")
            counts[key] = raw
        uncached_input_tokens = value.get(
            "uncached_input_tokens", value.get("effective_uncached_input_tokens")
        )
        if (
            not isinstance(uncached_input_tokens, int)
            or isinstance(uncached_input_tokens, bool)
            or uncached_input_tokens < 0
        ):
            raise ValueError(
                "effective_uncached_input_tokens must be a non-negative integer"
            )
        explicit_effective = value.get("effective_uncached_input_tokens")
        if (
            explicit_effective is not None
            and explicit_effective != uncached_input_tokens
        ):
            raise ValueError(
                "uncached_input_tokens and effective_uncached_input_tokens must match"
            )
        reported_input_tokens = value.get("input_tokens")
        if reported_input_tokens is not None and (
            not isinstance(reported_input_tokens, int)
            or isinstance(reported_input_tokens, bool)
            or reported_input_tokens < 0
        ):
            raise ValueError("input_tokens must be a non-negative integer")
        if reported_input_tokens is not None and reported_input_tokens != (
            uncached_input_tokens + counts["cache_read_tokens"]
        ):
            raise ValueError(
                "input_tokens must equal effective uncached plus cache-read tokens"
            )
        context_tokens = value.get("context_tokens")
        if context_tokens is not None and (
            not isinstance(context_tokens, int)
            or isinstance(context_tokens, bool)
            or context_tokens < 0
        ):
            raise ValueError("context_tokens must be a non-negative integer")
        price_variant = value.get("price_variant")
        if price_variant is not None and not isinstance(price_variant, str):
            raise ValueError("price_variant must be a string")
        protocol = value.get("protocol")
        if protocol is not None and (
            not isinstance(protocol, str)
            or protocol not in {"responses", "messages", "chat_completions"}
        ):
            raise ValueError("protocol must be a supported protocol string")
        logical_request_id = value.get("logical_request_id")
        if logical_request_id is not None and not isinstance(logical_request_id, str):
            raise ValueError("logical_request_id must be a string")
        upstream_attempts = value.get("upstream_attempts", value.get("attempts", 1))
        if (
            not isinstance(upstream_attempts, int)
            or isinstance(upstream_attempts, bool)
            or upstream_attempts <= 0
        ):
            raise ValueError("upstream_attempts must be a positive integer")
        reported_retries = value.get("retries")
        if reported_retries is not None and (
            not isinstance(reported_retries, int)
            or isinstance(reported_retries, bool)
            or reported_retries < 0
        ):
            raise ValueError("retries must be a non-negative integer")
        if reported_retries is not None and reported_retries != upstream_attempts - 1:
            raise ValueError("retries must equal upstream_attempts minus one")
        retry_reason = value.get("retry_reason")
        if retry_reason is not None and not isinstance(retry_reason, str):
            raise ValueError("retry_reason must be a string")
        hashes: dict[str, str | None] = {}
        for key in ("stable_prefix_hash", "request_shape_hash", "tool_schema_hash"):
            raw = value.get(key)
            if raw is not None and not isinstance(raw, str):
                raise ValueError(f"{key} must be a string")
            hashes[key] = raw
        timings: dict[str, float | None] = {}
        for key in ("ttft_ms", "duration_ms"):
            raw = value.get(key)
            if raw is not None and (
                not isinstance(raw, int | float) or isinstance(raw, bool) or raw < 0
            ):
                raise ValueError(f"{key} must be a non-negative number")
            timings[key] = float(raw) if raw is not None else None
        byte_counts: dict[str, int | None] = {}
        for key in ("bytes_in", "bytes_out"):
            raw = value.get(key)
            if raw is not None and (
                not isinstance(raw, int) or isinstance(raw, bool) or raw < 0
            ):
                raise ValueError(f"{key} must be a non-negative integer")
            byte_counts[key] = raw
        phase = value.get("phase")
        if phase is not None and (
            not isinstance(phase, str) or phase not in COMPACTION_PHASES
        ):
            raise ValueError("phase must be a supported compaction phase")
        compact_boundary_hash = value.get("compact_boundary_hash")
        if compact_boundary_hash is not None and not isinstance(
            compact_boundary_hash, str
        ):
            raise ValueError("compact_boundary_hash must be a string")
        reasoning_tokens = value.get("reasoning_tokens")
        if reasoning_tokens is not None and (
            not isinstance(reasoning_tokens, int)
            or isinstance(reasoning_tokens, bool)
            or reasoning_tokens < 0
        ):
            raise ValueError("reasoning_tokens must be a non-negative integer")
        learning_memory_ids = value.get("learning_memory_ids", ())
        if not isinstance(learning_memory_ids, list | tuple) or not all(
            isinstance(item, str) and item for item in learning_memory_ids
        ):
            raise ValueError(
                "learning_memory_ids must be an array of non-empty strings"
            )
        if len(learning_memory_ids) != len(set(learning_memory_ids)):
            raise ValueError("learning_memory_ids must not contain duplicates")
        return cls(
            model=model,
            context_tokens=context_tokens,
            price_variant=price_variant,
            protocol=protocol,
            logical_request_id=logical_request_id,
            upstream_attempts=upstream_attempts,
            retry_reason=retry_reason,
            stable_prefix_hash=hashes["stable_prefix_hash"],
            request_shape_hash=hashes["request_shape_hash"],
            tool_schema_hash=hashes["tool_schema_hash"],
            ttft_ms=timings["ttft_ms"],
            duration_ms=timings["duration_ms"],
            bytes_in=byte_counts["bytes_in"],
            bytes_out=byte_counts["bytes_out"],
            phase=phase,
            compact_boundary_hash=compact_boundary_hash,
            reasoning_tokens=reasoning_tokens,
            learning_memory_ids=tuple(learning_memory_ids),
            uncached_input_tokens=uncached_input_tokens,
            cache_read_tokens=counts["cache_read_tokens"],
            cache_write_tokens=counts["cache_write_tokens"],
            output_tokens=counts["output_tokens"],
        )


_STATIC_PRICES_FALLBACK: dict[str, GoPrice] = {
    "grok-4.5": GoPrice(2.00, 6.00, 0.30),
    "glm-5.3": GoPrice(1.40, 4.40, 0.26),
    "glm-5.2": GoPrice(1.40, 4.40, 0.26),
    "glm-5.1": GoPrice(1.40, 4.40, 0.26),
    "kimi-k3": GoPrice(3.00, 15.00, 0.30),
    "kimi-k2.7-code": GoPrice(0.95, 4.00, 0.19),
    "kimi-k2.6": GoPrice(0.95, 4.00, 0.16),
    "mimo-v2.5": GoPrice(0.14, 0.28, 0.0028),
    "mimo-v2.5-pro": GoPrice(0.435, 0.87, 0.003625),
    "minimax-m3": GoPrice(0.30, 1.20, 0.06),
    "minimax-m2.7": GoPrice(0.30, 1.20, 0.06, 0.375),
    "minimax-m2.5": GoPrice(0.30, 1.20, 0.06, 0.375),
    "muse-spark-1.2-contributor": GoPrice(0.10, 0.20, 0.002),
    "qwen3.8-max": GoPrice(2.00, 6.00, 0.25, 2.50),
    "qwen3.7-max": GoPrice(2.50, 7.50, 0.50, 3.125),
    "hy3": GoPrice(0.14, 0.58, 0.035),
    "ox-alpha-free": GoPrice(0.0, 0.0, 0.0),
    "x-preview-f-free": GoPrice(0.0, 0.0, 0.0),
}


def _load_pricing_fixture() -> dict[str, GoPrice]:
    fixture = Path(__file__).parents[1] / "fixtures" / "opencode_go_pricing.json"
    try:
        payload = json.loads(fixture.read_text("utf-8"))
    except OSError, json.JSONDecodeError:
        return _STATIC_PRICES_FALLBACK
    models = payload.get("models")
    if not isinstance(models, dict):
        return _STATIC_PRICES_FALLBACK
    prices: dict[str, GoPrice] = {}
    for model, raw in models.items():
        if not isinstance(model, str) or not isinstance(raw, dict):
            return _STATIC_PRICES_FALLBACK
        values = {
            key: raw.get(key)
            for key in ("input", "output", "cache_read", "cache_write")
        }
        if not all(isinstance(value, int | float) for value in values.values()):
            return _STATIC_PRICES_FALLBACK
        prices[model] = GoPrice(
            float(values["input"]),
            float(values["output"]),
            float(values["cache_read"]),
            float(values["cache_write"]),
        )
    return prices or _STATIC_PRICES_FALLBACK


_STATIC_PRICES = _load_pricing_fixture()


def pricing_for(usage: GoUsage) -> GoPrice:
    """Resolve the source-stamped Go price tier for one usage row."""

    if usage.model == "gpt-5.6-luna":
        context = _required_context(usage)
        return (
            GoPrice(0.20, 1.20, 0.02, 0.25)
            if context <= 272_000
            else GoPrice(0.40, 1.80, 0.04, 0.50)
        )
    if usage.model == "qwen3.7-plus":
        context = _required_context(usage)
        return (
            GoPrice(0.40, 1.60, 0.04, 0.50)
            if context <= 256_000
            else GoPrice(1.20, 4.80, 0.12, 1.50)
        )
    if usage.model == "qwen3.6-plus":
        context = _required_context(usage)
        return (
            GoPrice(0.50, 3.00, 0.05, 0.625)
            if context <= 256_000
            else GoPrice(2.00, 6.00, 0.20, 2.50)
        )
    if usage.model in {
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
    }:
        return _deepseek_price(usage)
    try:
        return _STATIC_PRICES[usage.model]
    except KeyError as exc:
        raise ValueError(
            f"no source-stamped Go price for model {usage.model!r}"
        ) from exc


def estimated_cost_usd(usage: GoUsage) -> float:
    """Estimate one request's Go dollar consumption from disjoint buckets."""

    price = pricing_for(usage)
    weighted = (
        usage.uncached_input_tokens * price.input
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
        + usage.output_tokens * price.output
    )
    return weighted / 1_000_000


def cache_read_share(usage: GoUsage) -> float:
    """Return cached-read share of uncached-plus-cached input tokens."""

    total = usage.uncached_input_tokens + usage.cache_read_tokens
    return usage.cache_read_tokens / total if total else 0.0


def canonical_prefix_json(request: dict[str, Any]) -> str:
    """Serialize only deterministic cache-prefix fields, excluding the suffix."""

    prefix: dict[str, Any] = {}
    for key in (
        "model",
        "instructions",
        "system",
        "tools",
        "tool_choice",
        "metadata",
        "cache_prefix",
    ):
        if key in request:
            prefix[key] = request[key]
    if "cache_prefix" not in request:
        for key in ("input", "messages"):
            value = request.get(key)
            if isinstance(value, list):
                prefix[f"{key}_prefix"] = value[:-1] if value else []
    return json.dumps(prefix, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_prefix_hash(request: dict[str, Any]) -> str:
    """Hash the canonical prefix without storing prompt content in a receipt."""

    return hashlib.sha256(canonical_prefix_json(request).encode("utf-8")).hexdigest()


def load_jsonl(path: str | Path) -> list[GoUsage]:
    """Load a redacted benchmark receipt JSONL file."""

    rows: list[GoUsage] = []
    for line_number, raw in enumerate(Path(path).read_text("utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"receipt line {line_number} must be an object")
        rows.append(GoUsage.from_mapping(value))
    if not rows:
        raise ValueError("receipt contains no usage rows")
    return rows


def load_receipt(path: str | Path) -> tuple[dict[str, Any], list[GoUsage]]:
    """Load optional metadata plus usage rows from one JSONL receipt."""

    metadata: dict[str, Any] = {}
    rows: list[GoUsage] = []
    for line_number, raw in enumerate(Path(path).read_text("utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"receipt line {line_number} must be an object")
        if "_receipt" in value:
            receipt = value["_receipt"]
            if not isinstance(receipt, dict):
                raise ValueError("_receipt metadata must be an object")
            metadata.update(receipt)
            continue
        rows.append(GoUsage.from_mapping(value))
    if not rows:
        raise ValueError("receipt contains no usage rows")
    commit_sha = metadata.get("commit_sha")
    if commit_sha is not None and (
        not isinstance(commit_sha, str) or len(commit_sha) not in {7, 40, 64}
    ):
        raise ValueError("receipt commit_sha must be a short or full SHA string")
    return metadata, rows


def summarize(rows: list[GoUsage]) -> dict[str, float | int | str]:
    """Return aggregate cache/cost metrics for a receipt."""

    if not rows:
        raise ValueError("cannot summarize an empty receipt")
    uncached = sum(row.uncached_input_tokens for row in rows)
    cache_read = sum(row.cache_read_tokens for row in rows)
    cache_write = sum(row.cache_write_tokens for row in rows)
    output = sum(row.output_tokens for row in rows)
    input_side = uncached + cache_read
    attempts = sum(row.upstream_attempts for row in rows)
    protocols = sorted({row.protocol for row in rows if row.protocol is not None})
    phases = sorted({row.phase for row in rows if row.phase is not None})
    compact_boundaries = [
        row.compact_boundary_hash for row in rows if row.compact_boundary_hash
    ]
    prefix_hashes = [row.stable_prefix_hash for row in rows if row.stable_prefix_hash]
    return {
        "requests": len(rows),
        "upstream_attempts": attempts,
        "retry_amplification": attempts / len(rows),
        "protocols": ",".join(protocols),
        "phases": ",".join(phases),
        "compact_boundary_hash_count": len(set(compact_boundaries)),
        "uncached_input_tokens": uncached,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "output_tokens": output,
        "cache_read_share": cache_read / input_side if input_side else 0.0,
        "estimated_cost_usd": sum(estimated_cost_usd(row) for row in rows),
        "stable_prefix_hash_count": len(prefix_hashes),
        "stable_prefix_unique_count": len(set(prefix_hashes)),
        "pricing_source_date": PRICING_SOURCE_DATE,
        "pricing_source_url": PRICING_SOURCE_URL,
    }


def compare_receipts(
    native_rows: list[GoUsage],
    fcc_rows: list[GoUsage],
) -> dict[str, Any]:
    """Compare native OpenCode and FCC receipts using estimated Go dollars."""

    _validate_comparable_receipts(native_rows, fcc_rows)
    native = summarize(native_rows)
    fcc = summarize(fcc_rows)
    native_cost = float(native["estimated_cost_usd"])
    fcc_cost = float(fcc["estimated_cost_usd"])
    native_uncached = int(native["uncached_input_tokens"])
    fcc_uncached = int(fcc["uncached_input_tokens"])
    native_attempts = int(native["upstream_attempts"])
    fcc_attempts = int(fcc["upstream_attempts"])
    if native_cost == 0:
        regression_pct = 0.0 if fcc_cost == 0 else float("inf")
    else:
        regression_pct = ((fcc_cost / native_cost) - 1.0) * 100.0
    cache_read_share_gap = (
        float(native["cache_read_share"]) - float(fcc["cache_read_share"])
    ) * 100.0
    comparison = {
        "native": native,
        "fcc": fcc,
        "estimated_cost_regression_pct": regression_pct,
        "cache_read_share_gap_percentage_points": cache_read_share_gap,
        "token_amplification": (
            fcc_uncached / native_uncached if native_uncached else float("inf")
        ),
        "retry_amplification_delta": float(fcc["retry_amplification"])
        - float(native["retry_amplification"]),
        "attempt_delta": fcc_attempts - native_attempts,
        "stable_prefix_match_rate": _prefix_match_rate(native_rows, fcc_rows),
    }
    if any(row.phase is not None for row in native_rows + fcc_rows):
        comparison["native_by_phase"] = summarize_phases(native_rows)
        comparison["fcc_by_phase"] = summarize_phases(fcc_rows)
    return comparison


def _validate_comparable_receipts(
    native_rows: list[GoUsage], fcc_rows: list[GoUsage]
) -> None:
    """Reject receipts that do not describe the same logical workload shape."""

    if len(native_rows) != len(fcc_rows):
        raise ValueError(
            "comparable receipts must contain the same number of usage rows"
        )

    native_phases = [row.phase for row in native_rows]
    fcc_phases = [row.phase for row in fcc_rows]
    if native_phases != fcc_phases:
        raise ValueError("comparable receipts must use the same phase sequence")

    native_models = [row.model for row in native_rows]
    fcc_models = [row.model for row in fcc_rows]
    if native_models != fcc_models:
        raise ValueError("comparable receipts must use the same model sequence")

    native_boundaries = [row.compact_boundary_hash is not None for row in native_rows]
    fcc_boundaries = [row.compact_boundary_hash is not None for row in fcc_rows]
    if native_boundaries != fcc_boundaries:
        raise ValueError("comparable receipts must use the same compact-boundary shape")


def summarize_phases(rows: list[GoUsage]) -> dict[str, dict[str, Any]]:
    """Summarize compact-boundary phases without mixing them together."""

    grouped: dict[str, list[GoUsage]] = {}
    for row in rows:
        if row.phase is None:
            continue
        grouped.setdefault(row.phase, []).append(row)
    if not grouped:
        raise ValueError("receipt contains no compaction phases")
    return {phase: summarize(group) for phase, group in sorted(grouped.items())}


def validate_compaction_economics(rows: list[GoUsage]) -> dict[str, Any]:
    """Validate the five-turn synthetic economics contract.

    The result is a metadata-only, machine-readable receipt. It intentionally
    validates the relationship between rows instead of claiming provider or
    client behavior that a synthetic fixture cannot prove.
    """

    if not rows:
        raise ValueError("compaction economics receipt contains no usage rows")

    phases = [row.phase for row in rows]
    mature_phases = phases[3:-1]
    expected_shape = (
        len(phases) >= len(COMPACTION_ECONOMICS_PHASE_SEQUENCE)
        and phases[:3] == list(COMPACTION_ECONOMICS_PHASE_SEQUENCE[:3])
        and bool(mature_phases)
        and all(phase == "mature_post_compact" for phase in mature_phases)
        and phases[-1] == "resume"
    )
    stable_prefixes = [row.stable_prefix_hash for row in rows]
    request_shapes = [row.request_shape_hash for row in rows]
    boundary_hashes = [row.compact_boundary_hash for row in rows]
    post_compact_prefixes = stable_prefixes[2:]
    learning_ids = [memory_id for row in rows for memory_id in row.learning_memory_ids]
    timings_valid = all(
        row.ttft_ms is None or row.duration_ms is None or row.duration_ms >= row.ttft_ms
        for row in rows
    )
    invariants = {
        "required_phase_sequence": expected_shape,
        "model_stable": len({row.model for row in rows}) == 1,
        "protocol_stable": len({row.protocol for row in rows}) == 1
        and rows[0].protocol is not None,
        "input_bucket_accounting": all(
            row.input_tokens
            == row.effective_uncached_input_tokens + row.cache_read_tokens
            for row in rows
        ),
        "stable_prefix_hashes_present": all(
            isinstance(value, str) and bool(value) for value in stable_prefixes
        ),
        "request_shape_hashes_present": all(
            isinstance(value, str) and bool(value) for value in request_shapes
        ),
        "request_shape_hashes_unique": len(set(request_shapes)) == len(rows)
        and all(isinstance(value, str) and bool(value) for value in request_shapes),
        "logical_request_ids_unique": len(
            {
                row.logical_request_id
                for row in rows
                if row.logical_request_id is not None
            }
        )
        == len(rows)
        and all(row.logical_request_id for row in rows),
        "compact_boundary_identity": len(set(boundary_hashes)) == 1
        and all(isinstance(value, str) and bool(value) for value in boundary_hashes),
        "post_compact_prefix_stable": len(set(post_compact_prefixes)) == 1
        and all(
            isinstance(value, str) and bool(value) for value in post_compact_prefixes
        ),
        "learning_memory_not_duplicated": len(learning_ids) == len(set(learning_ids)),
        "retry_amplification_bounded": sum(row.attempts for row in rows) == len(rows),
        "timings_ordered_when_available": timings_valid,
    }
    report = {
        "schema": COMPACTION_ECONOMICS_SCHEMA,
        "evidence": "synthetic-only",
        "passed": all(invariants.values()),
        "invariants": invariants,
        "summary": summarize(rows),
        "turns": [_economics_row_receipt(row) for row in rows],
    }
    return report


def assert_compaction_economics(rows: list[GoUsage]) -> dict[str, Any]:
    """Validate synthetic economics and raise with failed invariant names."""

    receipt = validate_compaction_economics(rows)
    if not receipt["passed"]:
        failed = [name for name, passed in receipt["invariants"].items() if not passed]
        raise ValueError("compaction economics failed: " + ", ".join(failed))
    return receipt


def load_compaction_economics_receipt(
    path: str | Path,
) -> tuple[dict[str, Any], list[GoUsage]]:
    """Load and validate one checked-in JSON synthetic economics receipt."""

    try:
        payload = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid compaction economics receipt: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("compaction economics receipt must be an object")
    leaked = sorted(_RAW_RECEIPT_FIELDS.intersection(payload))
    if leaked:
        raise ValueError(f"receipt must be metadata-only; forbidden fields: {leaked}")
    if payload.get("schema") != COMPACTION_ECONOMICS_SCHEMA:
        raise ValueError("unexpected compaction economics receipt schema")
    if payload.get("evidence") != "synthetic-only":
        raise ValueError("compaction economics receipt must be synthetic-only")
    turns = payload.get("turns")
    if not isinstance(turns, list):
        raise ValueError("compaction economics receipt turns must be an array")
    if not all(isinstance(turn, dict) for turn in turns):
        raise ValueError("compaction economics receipt turns must be objects")
    for turn in turns:
        leaked = sorted(_RAW_RECEIPT_FIELDS.intersection(turn))
        if leaked:
            raise ValueError(
                f"receipt must be metadata-only; forbidden fields: {leaked}"
            )
    schema_errors = sorted(
        Draft202012Validator(COMPACTION_ECONOMICS_RECEIPT_SCHEMA).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        raise ValueError(
            "invalid compaction economics receipt: " + schema_errors[0].message
        )
    rows = [GoUsage.from_mapping(turn) for turn in turns]
    model = payload.get("model")
    protocol = payload.get("protocol")
    if any(row.model != model for row in rows):
        raise ValueError("receipt model metadata does not match every turn")
    if any(row.protocol != protocol for row in rows):
        raise ValueError("receipt protocol metadata does not match every turn")
    assert_compaction_economics(rows)
    return payload, rows


def _economics_row_receipt(row: GoUsage) -> dict[str, Any]:
    """Serialize one usage row without retaining request or response content."""

    receipt: dict[str, Any] = {
        "model": row.model,
        "protocol": row.protocol,
        "logical_request_id": row.logical_request_id,
        "phase": row.phase,
        "input_tokens": row.input_tokens,
        "effective_uncached_input_tokens": row.effective_uncached_input_tokens,
        "cache_read_tokens": row.cache_read_tokens,
        "cache_write_tokens": row.cache_write_tokens,
        "output_tokens": row.output_tokens,
        "upstream_attempts": row.attempts,
        "retries": row.retries,
        "stable_prefix_hash": row.stable_prefix_hash,
        "request_shape_hash": row.request_shape_hash,
        "compact_boundary_hash": row.compact_boundary_hash,
        "learning_memory_ids": list(row.learning_memory_ids),
    }
    if row.retry_reason is not None:
        receipt["retry_reason"] = row.retry_reason
    if row.ttft_ms is not None:
        receipt["ttft_ms"] = row.ttft_ms
    if row.duration_ms is not None:
        receipt["duration_ms"] = row.duration_ms
    return receipt


def _prefix_match_rate(
    native_rows: list[GoUsage], fcc_rows: list[GoUsage]
) -> float | None:
    pairs = [
        (native.stable_prefix_hash, fcc.stable_prefix_hash)
        for native, fcc in zip(native_rows, fcc_rows, strict=False)
        if native.stable_prefix_hash and fcc.stable_prefix_hash
    ]
    if not pairs:
        return None
    return sum(native == fcc for native, fcc in pairs) / len(pairs)


def _required_context(usage: GoUsage) -> int:
    if usage.context_tokens is None:
        raise ValueError(f"context_tokens required for tiered model {usage.model!r}")
    return usage.context_tokens


def _deepseek_price(usage: GoUsage) -> GoPrice:
    variant = usage.price_variant
    if variant not in {"peak", "off_peak"}:
        raise ValueError(
            f"price_variant must be 'peak' or 'off_peak' for {usage.model!r}"
        )
    if usage.model == "deepseek-v4-pro":
        return (
            GoPrice(1.32, 3.96, 0.044)
            if variant == "peak"
            else GoPrice(0.66, 1.98, 0.022)
        )
    return (
        GoPrice(0.44, 1.32, 0.014) if variant == "peak" else GoPrice(0.22, 0.66, 0.007)
    )
