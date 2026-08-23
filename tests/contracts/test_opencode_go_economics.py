"""Deterministic tests for OpenCode Go cache-economic benchmark receipts."""

import pytest

from smoke.lib.opencode_go_economics import (
    GoUsage,
    cache_read_share,
    compare_receipts,
    estimated_cost_usd,
    pricing_for,
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
