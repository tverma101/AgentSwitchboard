"""OpenCode Go token-cost and cache-efficiency receipt helpers.

Pricing is intentionally source-stamped instead of fetched at benchmark time so a
receipt remains reproducible after OpenCode changes prices.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRICING_SOURCE_DATE = "2026-08-23"
PRICING_SOURCE_URL = "https://dev.opencode.ai/docs/go/"
RECEIPT_SCHEMA = "fcc.opencode-go-economics.v1"
SUPPORTED_PROTOCOLS = frozenset({"responses", "messages", "chat_completions"})
IMPLEMENTATION_LABELS = frozenset({"native", "harness"})
EVIDENCE_LABELS = frozenset({"synthetic-only", "live"})
COMPACTION_PHASES = frozenset(
    {"pre_compact", "compact_turn", "post_compact", "mature_post_compact", "resume"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{7}|[0-9a-f]{40}|[0-9a-f]{64})$")
_RAW_RECEIPT_FIELDS = frozenset(
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
        "text",
        "tool_arguments",
        "tool_result",
    }
)
_RECEIPT_METADATA_FIELDS = frozenset(
    {
        "commit_sha",
        "evidence",
        "fixture",
        "implementation",
        "model",
        "protocol",
        "schema",
        "source_date",
        "source_url",
    }
)
_REQUIRED_RECEIPT_METADATA_FIELDS = frozenset(
    {
        "commit_sha",
        "evidence",
        "fixture",
        "implementation",
        "model",
        "protocol",
        "schema",
    }
)
_USAGE_RECEIPT_FIELDS = frozenset(
    {
        "attempts",
        "bytes_in",
        "bytes_out",
        "cache_read_tokens",
        "cache_write_tokens",
        "compact_boundary_hash",
        "context_tokens",
        "duration_ms",
        "effective_uncached_input_tokens",
        "effective_uncached_tokens",
        "implementation",
        "input_tokens",
        "logical_request_id",
        "model",
        "output_tokens",
        "phase",
        "price_variant",
        "protocol",
        "reasoning_tokens",
        "request_shape_hash",
        "retries",
        "retry_reason",
        "stable_prefix_hash",
        "tool_schema_hash",
        "ttft_ms",
        "uncached_input_tokens",
        "upstream_attempts",
    }
)


def _validate_label(value: Any, field: str, *, max_length: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > max_length
        or "\n" in value
        or "\r" in value
    ):
        raise ValueError(f"{field} must be a non-empty single-line string")
    return value


def _validate_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")
    return value


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
    input_tokens: int | None = None
    effective_uncached_tokens: int | None = None
    implementation: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> GoUsage:
        leaked = sorted(_RAW_RECEIPT_FIELDS.intersection(value))
        if leaked:
            raise ValueError(
                "receipt rows must be metadata-only; forbidden raw fields: "
                + ", ".join(leaked)
            )
        unsupported = sorted(set(value) - _USAGE_RECEIPT_FIELDS)
        if unsupported:
            raise ValueError(
                "receipt rows must be metadata-only; unsupported fields: "
                + ", ".join(unsupported)
            )
        required = ("model", "cache_read_tokens", "cache_write_tokens", "output_tokens")
        missing = [key for key in required if key not in value]
        if not any(
            key in value
            for key in (
                "uncached_input_tokens",
                "effective_uncached_tokens",
                "effective_uncached_input_tokens",
                "input_tokens",
            )
        ):
            missing.append("uncached_input_tokens")
        if missing:
            raise ValueError(f"receipt row missing fields: {missing}")
        model = _validate_label(value["model"], "receipt model")
        counts: dict[str, int] = {}
        for key in required[1:]:
            raw = value[key]
            if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
                raise ValueError(f"{key} must be a non-negative integer")
            counts[key] = raw
        input_tokens = value.get("input_tokens")
        if input_tokens is not None and (
            not isinstance(input_tokens, int)
            or isinstance(input_tokens, bool)
            or input_tokens < 0
        ):
            raise ValueError("input_tokens must be a non-negative integer")
        uncached_input_tokens = value.get("uncached_input_tokens")
        effective_aliases = [
            value.get("effective_uncached_tokens"),
            value.get("effective_uncached_input_tokens"),
        ]
        effective_values = [item for item in effective_aliases if item is not None]
        if any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in effective_values
        ):
            raise ValueError("effective_uncached_tokens must be a non-negative integer")
        if any(item != effective_values[0] for item in effective_values[1:]):
            raise ValueError(
                "effective_uncached_tokens aliases must contain the same value"
            )
        if uncached_input_tokens is not None and (
            not isinstance(uncached_input_tokens, int)
            or isinstance(uncached_input_tokens, bool)
            or uncached_input_tokens < 0
        ):
            raise ValueError("uncached_input_tokens must be a non-negative integer")
        if (
            uncached_input_tokens is not None
            and effective_values
            and uncached_input_tokens != effective_values[0]
        ):
            raise ValueError(
                "uncached_input_tokens and effective_uncached_tokens must match"
            )
        raw_uncached = (
            uncached_input_tokens
            if uncached_input_tokens is not None
            else effective_values[0]
            if effective_values
            else None
        )
        if raw_uncached is None:
            if input_tokens is None:
                raise ValueError(
                    "receipt row missing fields: ['uncached_input_tokens']"
                )
            if input_tokens < counts["cache_read_tokens"]:
                raise ValueError(
                    "input_tokens cannot be smaller than cache_read_tokens"
                )
            raw_uncached = input_tokens - counts["cache_read_tokens"]
        if (
            not isinstance(raw_uncached, int)
            or isinstance(raw_uncached, bool)
            or raw_uncached < 0
        ):
            raise ValueError("uncached_input_tokens must be a non-negative integer")
        if input_tokens is not None and input_tokens != (
            raw_uncached + counts["cache_read_tokens"]
        ):
            raise ValueError("input_tokens must equal uncached plus cache-read tokens")
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
            not isinstance(protocol, str) or protocol not in SUPPORTED_PROTOCOLS
        ):
            raise ValueError("protocol must be a supported protocol string")
        logical_request_id = value.get("logical_request_id")
        if logical_request_id is not None:
            _validate_label(logical_request_id, "logical_request_id", max_length=128)
        attempt_aliases = [value.get("upstream_attempts"), value.get("attempts")]
        attempt_values = [item for item in attempt_aliases if item is not None]
        if any(
            not isinstance(item, int) or isinstance(item, bool) or item <= 0
            for item in attempt_values
        ):
            raise ValueError("upstream_attempts must be a positive integer")
        if any(item != attempt_values[0] for item in attempt_values[1:]):
            raise ValueError("upstream_attempts and attempts must match")
        upstream_attempts = attempt_values[0] if attempt_values else 1
        if (
            not isinstance(upstream_attempts, int)
            or isinstance(upstream_attempts, bool)
            or upstream_attempts <= 0
        ):
            raise ValueError("upstream_attempts must be a positive integer")
        retries = value.get("retries")
        if retries is not None and (
            not isinstance(retries, int) or isinstance(retries, bool) or retries < 0
        ):
            raise ValueError("retries must be a non-negative integer")
        if retries is not None and retries != upstream_attempts - 1:
            raise ValueError("retries must equal upstream_attempts minus one")
        retry_reason = value.get("retry_reason")
        if retry_reason is not None:
            _validate_label(retry_reason, "retry_reason", max_length=128)
        hashes: dict[str, str | None] = {}
        for key in ("stable_prefix_hash", "request_shape_hash", "tool_schema_hash"):
            raw = value.get(key)
            hashes[key] = _validate_sha256(raw, key) if raw is not None else None
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
        if compact_boundary_hash is not None:
            compact_boundary_hash = _validate_sha256(
                compact_boundary_hash, "compact_boundary_hash"
            )
        reasoning_tokens = value.get("reasoning_tokens")
        if reasoning_tokens is not None and (
            not isinstance(reasoning_tokens, int)
            or isinstance(reasoning_tokens, bool)
            or reasoning_tokens < 0
        ):
            raise ValueError("reasoning_tokens must be a non-negative integer")
        implementation = value.get("implementation")
        if implementation is not None and (
            not isinstance(implementation, str)
            or implementation not in IMPLEMENTATION_LABELS
        ):
            raise ValueError("implementation must be 'native' or 'harness'")
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
            input_tokens=input_tokens,
            effective_uncached_tokens=raw_uncached,
            implementation=implementation,
            uncached_input_tokens=raw_uncached,
            cache_read_tokens=counts["cache_read_tokens"],
            cache_write_tokens=counts["cache_write_tokens"],
            output_tokens=counts["output_tokens"],
        )

    @property
    def total_input_tokens(self) -> int:
        """Return the total input represented by both disjoint input buckets."""

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


def canonical_request_shape_json(request: dict[str, Any]) -> str:
    """Serialize the request envelope while excluding volatile correlation fields."""

    shape: dict[str, Any] = {}
    for key in (
        "model",
        "instructions",
        "system",
        "tools",
        "tool_choice",
        "metadata",
        "input",
        "messages",
        "max_output_tokens",
        "temperature",
        "top_p",
        "reasoning",
        "stream",
    ):
        if key in request:
            shape[key] = request[key]
    return json.dumps(shape, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_shape_hash(request: dict[str, Any]) -> str:
    """Hash the canonical request envelope without retaining request content."""

    return hashlib.sha256(
        canonical_request_shape_json(request).encode("utf-8")
    ).hexdigest()


def tool_schema_hash(request: dict[str, Any]) -> str:
    """Hash the ordered tool schema independently of the request body."""

    tools = request.get("tools", [])
    serialized = json.dumps(
        tools, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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
    """Load one strict, metadata-only JSONL receipt."""

    metadata: dict[str, Any] = {}
    rows: list[GoUsage] = []
    metadata_seen = False
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
            if set(value) != {"_receipt"}:
                raise ValueError(
                    "receipt metadata line cannot contain usage or content fields"
                )
            if metadata_seen:
                raise ValueError(
                    "receipt must contain exactly one _receipt metadata line"
                )
            receipt = value["_receipt"]
            if not isinstance(receipt, dict):
                raise ValueError("_receipt metadata must be an object")
            metadata = dict(receipt)
            metadata_seen = True
            continue
        rows.append(GoUsage.from_mapping(value))
    if not rows:
        raise ValueError("receipt contains no usage rows")
    _validate_receipt_metadata(metadata)
    _validate_receipt_rows(rows, metadata=metadata, require_logical_request_ids=True)
    return metadata, rows


def _validate_receipt_metadata(metadata: dict[str, Any]) -> None:
    unsupported = sorted(set(metadata) - _RECEIPT_METADATA_FIELDS)
    if unsupported:
        raise ValueError(
            "receipt metadata must be metadata-only; unsupported fields: "
            + ", ".join(unsupported)
        )
    missing = sorted(_REQUIRED_RECEIPT_METADATA_FIELDS - set(metadata))
    if missing:
        raise ValueError(f"receipt metadata missing fields: {missing}")
    if metadata["schema"] != RECEIPT_SCHEMA:
        raise ValueError(f"receipt schema must be {RECEIPT_SCHEMA!r}")
    commit_sha = metadata["commit_sha"]
    if not isinstance(commit_sha, str) or _COMMIT_RE.fullmatch(commit_sha) is None:
        raise ValueError(
            "receipt commit_sha must be a short or full lowercase SHA string"
        )
    _validate_label(metadata["fixture"], "receipt fixture")
    _validate_label(metadata["model"], "receipt metadata model")
    protocol = metadata["protocol"]
    if not isinstance(protocol, str) or protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError("receipt metadata protocol must be supported")
    implementation = metadata["implementation"]
    if (
        not isinstance(implementation, str)
        or implementation not in IMPLEMENTATION_LABELS
    ):
        raise ValueError(
            "receipt metadata implementation must be 'native' or 'harness'"
        )
    evidence = metadata["evidence"]
    if not isinstance(evidence, str) or evidence not in EVIDENCE_LABELS:
        raise ValueError("receipt metadata evidence must be 'synthetic-only' or 'live'")
    for key in ("source_date", "source_url"):
        if key in metadata:
            _validate_label(metadata[key], f"receipt metadata {key}")


def _validate_receipt_rows(
    rows: list[GoUsage],
    *,
    metadata: dict[str, Any] | None = None,
    require_logical_request_ids: bool = False,
) -> None:
    if not rows:
        raise ValueError("receipt contains no usage rows")
    seen_request_ids: set[str] = set()
    for index, row in enumerate(rows, 1):
        if row.stable_prefix_hash is None:
            raise ValueError(f"receipt row {index} missing stable_prefix_hash")
        _validate_sha256(row.stable_prefix_hash, "stable_prefix_hash")
        if row.request_shape_hash is None:
            raise ValueError(f"receipt row {index} missing request_shape_hash")
        _validate_sha256(row.request_shape_hash, "request_shape_hash")
        if row.protocol is None:
            raise ValueError(f"receipt row {index} missing protocol")
        if metadata is not None:
            if row.model != metadata["model"]:
                raise ValueError(f"receipt row {index} model does not match metadata")
            if row.protocol != metadata["protocol"]:
                raise ValueError(
                    f"receipt row {index} protocol does not match metadata"
                )
            if row.implementation != metadata["implementation"]:
                raise ValueError(
                    f"receipt row {index} implementation does not match metadata"
                )
        if row.logical_request_id is None:
            if require_logical_request_ids:
                raise ValueError(f"receipt row {index} missing logical_request_id")
        elif row.logical_request_id in seen_request_ids:
            raise ValueError(
                f"receipt contains duplicate logical_request_id {row.logical_request_id!r}"
            )
        else:
            seen_request_ids.add(row.logical_request_id)


def summarize(rows: list[GoUsage]) -> dict[str, Any]:
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
    request_hashes = [row.request_shape_hash for row in rows if row.request_shape_hash]
    tool_hashes = [row.tool_schema_hash for row in rows if row.tool_schema_hash]
    return {
        "requests": len(rows),
        "upstream_attempts": attempts,
        "retries": attempts - len(rows),
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
        "request_shape_hash_count": len(request_hashes),
        "request_shape_unique_count": len(set(request_hashes)),
        "tool_schema_hash_count": len(tool_hashes),
        "tool_schema_unique_count": len(set(tool_hashes)),
        "pricing_source_date": PRICING_SOURCE_DATE,
        "pricing_source_url": PRICING_SOURCE_URL,
    }


def compare_receipts(
    native_rows: list[GoUsage],
    harness_rows: list[GoUsage],
    *,
    native_metadata: dict[str, Any] | None = None,
    harness_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare native OpenCode and Harness receipts using metadata-only evidence."""

    if (native_metadata is None) != (harness_metadata is None):
        raise ValueError(
            "native and Harness receipt metadata must be supplied together"
        )
    if native_metadata is not None and harness_metadata is not None:
        _validate_receipt_metadata(native_metadata)
        _validate_receipt_metadata(harness_metadata)
        _validate_receipt_rows(
            native_rows, metadata=native_metadata, require_logical_request_ids=True
        )
        _validate_receipt_rows(
            harness_rows, metadata=harness_metadata, require_logical_request_ids=True
        )
        _validate_comparable_metadata(native_metadata, harness_metadata)
    else:
        _validate_receipt_rows(native_rows)
        _validate_receipt_rows(harness_rows)
    _validate_comparable_receipts(native_rows, harness_rows)
    native = summarize(native_rows)
    harness = summarize(harness_rows)
    native_cost = float(native["estimated_cost_usd"])
    harness_cost = float(harness["estimated_cost_usd"])
    native_uncached = int(native["uncached_input_tokens"])
    harness_uncached = int(harness["uncached_input_tokens"])
    native_attempts = int(native["upstream_attempts"])
    harness_attempts = int(harness["upstream_attempts"])
    if native_cost == 0:
        regression_pct = 0.0 if harness_cost == 0 else float("inf")
    else:
        regression_pct = ((harness_cost / native_cost) - 1.0) * 100.0
    native_implementation = (
        native_metadata["implementation"] if native_metadata is not None else "native"
    )
    harness_implementation = (
        harness_metadata["implementation"]
        if harness_metadata is not None
        else "harness"
    )
    comparison: dict[str, Any] = {
        "implementations": {
            "native": native_implementation,
            "harness": harness_implementation,
        },
        "native": native,
        "harness": harness,
        # Keep the old key for callers that used the PR's FCC terminology.
        "fcc": harness,
        "estimated_cost_regression_pct": regression_pct,
        "cache_read_share_gap_percentage_points": (
            float(native["cache_read_share"]) - float(harness["cache_read_share"])
        )
        * 100.0,
        "token_amplification": (
            harness_uncached / native_uncached if native_uncached else float("inf")
        ),
        "retry_amplification_delta": float(harness["retry_amplification"])
        - float(native["retry_amplification"]),
        "attempt_delta": harness_attempts - native_attempts,
        "stable_prefix_match_rate": _prefix_match_rate(native_rows, harness_rows),
        "envelope": {
            "request_shape_match_rate": _hash_match_rate(
                native_rows, harness_rows, "request_shape_hash"
            ),
            "stable_prefix_match_rate": _hash_match_rate(
                native_rows, harness_rows, "stable_prefix_hash"
            ),
            "tool_schema_match_rate": _hash_match_rate(
                native_rows, harness_rows, "tool_schema_hash"
            ),
        },
    }
    if native_metadata is not None and harness_metadata is not None:
        comparison["evidence"] = {
            "native": native_metadata["evidence"],
            "harness": harness_metadata["evidence"],
            "comparison": native_metadata["evidence"],
        }
    else:
        comparison["evidence"] = {
            "native": "unverified",
            "harness": "unverified",
            "comparison": "unverified",
        }
    if any(row.phase is not None for row in native_rows + harness_rows):
        comparison["native_by_phase"] = summarize_phases(native_rows)
        comparison["harness_by_phase"] = summarize_phases(harness_rows)
        comparison["fcc_by_phase"] = comparison["harness_by_phase"]
    return comparison


def _validate_comparable_metadata(
    native_metadata: dict[str, Any], harness_metadata: dict[str, Any]
) -> None:
    if native_metadata["implementation"] != "native":
        raise ValueError("native receipt metadata must be labeled 'native'")
    if harness_metadata["implementation"] != "harness":
        raise ValueError("Harness receipt metadata must be labeled 'harness'")
    for key in ("schema", "model", "protocol", "fixture", "evidence"):
        if native_metadata[key] != harness_metadata[key]:
            raise ValueError(
                f"native and Harness receipts must use the same {key} metadata"
            )


def _validate_comparable_receipts(
    native_rows: list[GoUsage], harness_rows: list[GoUsage]
) -> None:
    """Reject receipts that do not describe the same logical workload shape."""

    if len(native_rows) != len(harness_rows):
        raise ValueError(
            "comparable receipts must contain the same number of usage rows"
        )
    native_phases = [row.phase for row in native_rows]
    harness_phases = [row.phase for row in harness_rows]
    if native_phases != harness_phases:
        raise ValueError("comparable receipts must use the same phase sequence")
    native_models = [row.model for row in native_rows]
    harness_models = [row.model for row in harness_rows]
    if native_models != harness_models:
        raise ValueError("comparable receipts must use the same model sequence")
    native_protocols = [row.protocol for row in native_rows]
    harness_protocols = [row.protocol for row in harness_rows]
    if native_protocols != harness_protocols:
        raise ValueError("comparable receipts must use the same protocol sequence")
    native_tiers = [(row.context_tokens, row.price_variant) for row in native_rows]
    harness_tiers = [(row.context_tokens, row.price_variant) for row in harness_rows]
    if native_tiers != harness_tiers:
        raise ValueError("comparable receipts must use the same pricing tier inputs")
    native_boundaries = [row.compact_boundary_hash is not None for row in native_rows]
    harness_boundaries = [row.compact_boundary_hash is not None for row in harness_rows]
    if native_boundaries != harness_boundaries:
        raise ValueError("comparable receipts must use the same compact-boundary shape")
    for native, harness in zip(native_rows, harness_rows, strict=True):
        if (
            native.compact_boundary_hash is not None
            and native.compact_boundary_hash != harness.compact_boundary_hash
        ):
            raise ValueError("comparable receipts must use the same compact boundary")
    native_implementations = {
        row.implementation for row in native_rows if row.implementation is not None
    }
    harness_implementations = {
        row.implementation for row in harness_rows if row.implementation is not None
    }
    if native_implementations and native_implementations != {"native"}:
        raise ValueError("native receipt rows must be labeled native")
    if harness_implementations and harness_implementations != {"harness"}:
        raise ValueError("Harness receipt rows must be labeled harness")


def summarize_phases(rows: list[GoUsage]) -> dict[str, dict[str, Any]]:
    """Summarize compact-boundary phases without mixing them together."""

    grouped: dict[str, list[GoUsage]] = {}
    for row in rows:
        if row.phase is not None:
            grouped.setdefault(row.phase, []).append(row)
    if not grouped:
        raise ValueError("receipt contains no compaction phases")
    return {phase: summarize(group) for phase, group in sorted(grouped.items())}


def _hash_match_rate(
    native_rows: list[GoUsage], harness_rows: list[GoUsage], field: str
) -> float | None:
    values = [
        (getattr(native, field), getattr(harness, field))
        for native, harness in zip(native_rows, harness_rows, strict=True)
    ]
    if not values or not all(
        native is not None and harness is not None for native, harness in values
    ):
        return None
    return sum(native == harness for native, harness in values) / len(values)


def _prefix_match_rate(
    native_rows: list[GoUsage], harness_rows: list[GoUsage]
) -> float | None:
    return _hash_match_rate(native_rows, harness_rows, "stable_prefix_hash")


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
