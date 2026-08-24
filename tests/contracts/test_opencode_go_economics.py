"""Deterministic tests for OpenCode Go cache-economic benchmark receipts."""

from dataclasses import replace

import pytest

from smoke.lib.opencode_go_economics import (
    GoUsage,
    cache_read_share,
    compare_receipts,
    estimated_cost_usd,
    load_receipt,
    pricing_for,
    stable_prefix_hash,
    summarize_phases,
)


def _muse(*, uncached: int = 620, cached: int = 71_400) -> GoUsage:
    return GoUsage(
        model="muse-spark-1.2-contributor",
        uncached_input_tokens=uncached,
        cache_read_tokens=cached,
        cache_write_tokens=0,
        output_tokens=300,
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
    assert comparison["cache_read_share_gap_percentage_points"] > 0.0
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


def test_compaction_phase_receipts_are_validated_and_summarized_separately() -> None:
    rows = [
        _muse(uncached=620, cached=71_400),
        _muse(uncached=650, cached=71_370),
        _muse(uncached=700, cached=71_320),
    ]
    rows = [
        replace(rows[0], phase="pre_compact", compact_boundary_hash="boundary-1"),
        replace(rows[1], phase="compact_turn", compact_boundary_hash="boundary-1"),
        replace(rows[2], phase="resume", compact_boundary_hash="boundary-1"),
    ]

    summaries = summarize_phases(rows)

    assert list(summaries) == ["compact_turn", "pre_compact", "resume"]
    assert summaries["resume"]["requests"] == 1
    assert summaries["resume"]["compact_boundary_hash_count"] == 1


def test_compaction_phase_rejects_unknown_phase() -> None:
    with pytest.raises(ValueError, match="compaction phase"):
        GoUsage.from_mapping(
            {
                "model": "muse-spark-1.2-contributor",
                "uncached_input_tokens": 1,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "output_tokens": 1,
                "phase": "after_everything",
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


def test_compare_receipts_reports_token_and_retry_amplification() -> None:
    native = [
        replace(
            _muse(),
            protocol="responses",
            upstream_attempts=1,
            stable_prefix_hash="same",
        )
    ]
    fcc = [
        replace(
            _muse(uncached=1_000, cached=71_020),
            protocol="responses",
            upstream_attempts=2,
            stable_prefix_hash="same",
        )
    ]

    comparison = compare_receipts(native, fcc)

    assert comparison["token_amplification"] > 1.0
    assert comparison["attempt_delta"] == 1
    assert comparison["retry_amplification_delta"] == pytest.approx(1.0)
    assert comparison["stable_prefix_match_rate"] == 1.0


def test_load_receipt_preserves_commit_and_protocol_metadata(tmp_path) -> None:
    receipt = tmp_path / "receipt.jsonl"
    receipt.write_text(
        "\n".join(
            (
                '{"_receipt":{"commit_sha":"abcdef1","protocol":"responses"}}',
                '{"model":"muse-spark-1.2-contributor","uncached_input_tokens":1,"cache_read_tokens":2,"cache_write_tokens":0,"output_tokens":3,"protocol":"responses","upstream_attempts":1}',
            )
        )
        + "\n",
        encoding="utf-8",
    )

    metadata, rows = load_receipt(receipt)

    assert metadata == {"commit_sha": "abcdef1", "protocol": "responses"}
    assert rows[0].protocol == "responses"
