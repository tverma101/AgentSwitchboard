"""Deterministic tests for OpenCode Go cache-economic benchmark receipts."""

from dataclasses import replace
from pathlib import Path

import pytest

from smoke.lib.opencode_go_economics import (
    GoUsage,
    cache_read_share,
    compare_receipts,
    estimated_cost_usd,
    load_receipt,
    pricing_for,
    request_shape_hash,
    stable_prefix_hash,
    tool_schema_hash,
)

_FIXTURES = Path(__file__).parents[2] / "smoke" / "fixtures"


def _muse(
    *,
    uncached: int = 620,
    cached: int = 71_400,
    model: str = "muse-spark-1.2-contributor",
    attempts: int = 1,
    request_id: str | None = None,
    implementation: str | None = None,
) -> GoUsage:
    return GoUsage(
        model=model,
        uncached_input_tokens=uncached,
        cache_read_tokens=cached,
        cache_write_tokens=0,
        output_tokens=300,
        protocol="responses",
        logical_request_id=request_id,
        upstream_attempts=attempts,
        stable_prefix_hash="a" * 64,
        request_shape_hash="b" * 64,
        tool_schema_hash="c" * 64,
        implementation=implementation,
    )


def test_muse_published_typical_request_is_about_99_percent_cached() -> None:
    usage = _muse()

    assert cache_read_share(usage) == pytest.approx(0.99139, abs=0.00001)
    assert estimated_cost_usd(usage) == pytest.approx(0.0002648)


def test_muse_cache_loss_materially_increases_estimated_cost() -> None:
    native = [_muse() for _ in range(10)]
    fcc = [_muse(uncached=5_000, cached=67_020) for _ in range(10)]

    comparison = compare_receipts(native, fcc)

    assert comparison["fcc"]["cache_read_share"] < 0.98
    assert comparison["estimated_cost_regression_pct"] > 5.0


def test_equal_receipts_have_zero_estimated_cost_regression() -> None:
    native = [_muse() for _ in range(3)]
    comparison = compare_receipts(native, list(native))

    assert comparison["estimated_cost_regression_pct"] == pytest.approx(0.0)


def test_qwen_plus_uses_more_expensive_tier_above_256k() -> None:
    low = GoUsage("qwen3.7-plus", 1, 0, 0, 0, context_tokens=256_000)
    high = GoUsage("qwen3.7-plus", 1, 0, 0, 0, context_tokens=256_001)

    assert pricing_for(low).input == 0.40
    assert pricing_for(high).input == 1.20


def test_luna_uses_272k_tier_boundary() -> None:
    low = GoUsage("gpt-5.6-luna", 1, 0, 0, 0, context_tokens=272_000)
    high = GoUsage("gpt-5.6-luna", 1, 0, 0, 0, context_tokens=272_001)

    assert pricing_for(low).input == 0.20
    assert pricing_for(high).input == 0.40


def test_deepseek_requires_explicit_peak_variant() -> None:
    usage = GoUsage("deepseek-v4-flash", 1, 0, 0, 0)

    with pytest.raises(ValueError, match="price_variant"):
        pricing_for(usage)


def test_usage_rejects_overlapping_or_invalid_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        GoUsage.from_mapping(
            {
                "model": "muse-spark-1.2-contributor",
                "uncached_input_tokens": -1,
                "cache_read_tokens": 10,
                "cache_write_tokens": 0,
                "output_tokens": 1,
            }
        )


def test_usage_rejects_raw_content_and_unknown_fields() -> None:
    row = {
        "model": "muse-spark-1.2-contributor",
        "uncached_input_tokens": 1,
        "cache_read_tokens": 2,
        "cache_write_tokens": 0,
        "output_tokens": 3,
    }

    with pytest.raises(ValueError, match="forbidden raw fields"):
        GoUsage.from_mapping(row | {"input": "secret prompt"})
    with pytest.raises(ValueError, match="unsupported fields"):
        GoUsage.from_mapping(row | {"unexpected": 1})


def test_usage_normalizes_input_aliases_and_requires_consistent_retries() -> None:
    row = GoUsage.from_mapping(
        {
            "model": "muse-spark-1.2-contributor",
            "input_tokens": 12,
            "cache_read_tokens": 5,
            "cache_write_tokens": 0,
            "output_tokens": 3,
            "attempts": 2,
            "retries": 1,
        }
    )

    assert row.uncached_input_tokens == 7
    assert row.total_input_tokens == 12
    assert row.attempts == 2
    assert row.retries == 1

    with pytest.raises(ValueError, match="must equal upstream_attempts"):
        GoUsage.from_mapping(
            {
                "model": "muse-spark-1.2-contributor",
                "uncached_input_tokens": 1,
                "cache_read_tokens": 2,
                "cache_write_tokens": 0,
                "output_tokens": 3,
                "upstream_attempts": 2,
                "retries": 0,
            }
        )


def test_cache_read_share_excludes_cache_write_from_the_ratio() -> None:
    usage = _muse(uncached=1_000, cached=9_000)
    usage = replace(usage, cache_write_tokens=10_000)

    assert cache_read_share(usage) == pytest.approx(0.9)


def test_stable_prefix_hash_ignores_appended_suffix_but_detects_tool_reordering() -> (
    None
):
    prefix = {
        "model": "muse-spark-1.2-contributor",
        "system": [{"type": "text", "text": "stable"}],
        "tools": [{"name": "Read"}, {"name": "Write"}],
        "cache_prefix": {"history": ["turn-1", "tool-result-1"]},
        "messages": [{"role": "user", "content": "next"}],
        "request_id": "volatile-1",
        "timestamp": "volatile-1",
    }
    next_turn = {
        **prefix,
        "messages": [
            {"role": "user", "content": "next"},
            {"role": "user", "content": "appended"},
        ],
        "request_id": "volatile-2",
        "timestamp": "volatile-2",
    }
    shuffled_tools = {
        **next_turn,
        "tools": [{"name": "Write"}, {"name": "Read"}],
    }

    assert stable_prefix_hash(prefix) == stable_prefix_hash(next_turn)
    assert stable_prefix_hash(next_turn) != stable_prefix_hash(shuffled_tools)


def test_request_and_tool_hashes_exclude_volatile_ids_and_preserve_shape() -> None:
    request = {
        "model": "muse-spark-1.2-contributor",
        "system": [{"type": "text", "text": "stable"}],
        "tools": [{"name": "Read"}, {"name": "Write"}],
        "messages": [{"role": "user", "content": "next"}],
        "request_id": "volatile-1",
        "timestamp": "volatile-1",
    }
    with_new_volatiles = {
        **request,
        "request_id": "volatile-2",
        "timestamp": "volatile-2",
    }
    reordered_tools = {**request, "tools": list(reversed(request["tools"]))}

    assert request_shape_hash(request) == request_shape_hash(with_new_volatiles)
    assert request_shape_hash(request) != request_shape_hash(
        {**request, "temperature": 0.2}
    )
    assert tool_schema_hash(request) != tool_schema_hash(reordered_tools)


def test_compare_receipts_reports_token_and_retry_amplification() -> None:
    native = [
        replace(
            _muse(),
            upstream_attempts=1,
            stable_prefix_hash="d" * 64,
        )
    ]
    fcc = [
        replace(
            _muse(uncached=1_000, cached=71_020),
            upstream_attempts=2,
            stable_prefix_hash="d" * 64,
        )
    ]

    comparison = compare_receipts(native, fcc)

    assert comparison["token_amplification"] > 1.0
    assert comparison["attempt_delta"] == 1
    assert comparison["retry_amplification_delta"] == pytest.approx(1.0)
    assert comparison["stable_prefix_match_rate"] == 1.0


def _metadata(implementation: str) -> dict[str, str]:
    return {
        "schema": "fcc.opencode-go-economics.v1",
        "commit_sha": "a" * 40 if implementation == "native" else "b" * 40,
        "model": "muse-spark-1.2-contributor",
        "protocol": "responses",
        "fixture": "muse-stable-prefix-v1",
        "implementation": implementation,
        "evidence": "synthetic-only",
    }


def test_compare_receipts_requires_same_metadata_workload() -> None:
    native = [_muse(request_id="turn-001", implementation="native")]
    harness = [_muse(request_id="turn-001", implementation="harness")]

    comparison = compare_receipts(
        native,
        harness,
        native_metadata=_metadata("native"),
        harness_metadata=_metadata("harness"),
    )

    assert comparison["implementations"] == {"native": "native", "harness": "harness"}
    assert comparison["evidence"] == {
        "native": "synthetic-only",
        "harness": "synthetic-only",
        "comparison": "synthetic-only",
    }
    assert comparison["envelope"] == {
        "request_shape_match_rate": 1.0,
        "stable_prefix_match_rate": 1.0,
        "tool_schema_match_rate": 1.0,
    }

    mismatched = _metadata("harness") | {"fixture": "different-workload"}
    with pytest.raises(ValueError, match="same fixture"):
        compare_receipts(
            native,
            harness,
            native_metadata=_metadata("native"),
            harness_metadata=mismatched,
        )


def test_compare_receipts_rejects_different_row_shapes() -> None:
    native = [_muse(request_id="turn-001")]
    harness = [replace(_muse(request_id="turn-001"), model="other-model")]

    with pytest.raises(ValueError, match="same model sequence"):
        compare_receipts(native, harness)


def test_checked_in_synthetic_receipts_are_strict_and_non_live() -> None:
    native_metadata, native_rows = load_receipt(
        _FIXTURES / "opencode_go_native.sample.jsonl"
    )
    harness_metadata, harness_rows = load_receipt(
        _FIXTURES / "opencode_go_fcc.sample.jsonl"
    )

    comparison = compare_receipts(
        native_rows,
        harness_rows,
        native_metadata=native_metadata,
        harness_metadata=harness_metadata,
    )

    assert comparison["evidence"]["comparison"] == "synthetic-only"
    assert comparison["cache_read_share_gap_percentage_points"] == pytest.approx(0.0)
    assert comparison["retry_amplification_delta"] == pytest.approx(0.0)
    assert comparison["envelope"]["request_shape_match_rate"] == 1.0


def test_load_receipt_preserves_commit_and_protocol_metadata(tmp_path) -> None:
    receipt = tmp_path / "receipt.jsonl"
    receipt.write_text(
        "\n".join(
            (
                '{"_receipt":{"schema":"fcc.opencode-go-economics.v1","commit_sha":"abcdef1","model":"muse-spark-1.2-contributor","protocol":"responses","fixture":"unit-v1","implementation":"native","evidence":"synthetic-only"}}',
                '{"model":"muse-spark-1.2-contributor","uncached_input_tokens":1,"cache_read_tokens":2,"cache_write_tokens":0,"output_tokens":3,"protocol":"responses","logical_request_id":"turn-001","upstream_attempts":1,"retries":0,"stable_prefix_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","request_shape_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","implementation":"native"}',
            )
        )
        + "\n",
        encoding="utf-8",
    )

    metadata, rows = load_receipt(receipt)

    assert metadata == {
        "schema": "fcc.opencode-go-economics.v1",
        "commit_sha": "abcdef1",
        "model": "muse-spark-1.2-contributor",
        "protocol": "responses",
        "fixture": "unit-v1",
        "implementation": "native",
        "evidence": "synthetic-only",
    }
    assert rows[0].protocol == "responses"
