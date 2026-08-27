"""Deterministic tests for OpenCode Go cache-economic benchmark receipts."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from smoke.lib.opencode_go_economics import (
    COMPACTION_ECONOMICS_RECEIPT_SCHEMA,
    COMPACTION_ECONOMICS_SCHEMA,
    GoUsage,
    assert_compaction_economics,
    cache_read_share,
    compare_receipts,
    estimated_cost_usd,
    load_compaction_economics_receipt,
    load_receipt,
    pricing_for,
    stable_prefix_hash,
    summarize_phases,
    validate_compaction_economics,
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


def test_compaction_economics_schema_is_valid_json_schema() -> None:
    Draft202012Validator.check_schema(COMPACTION_ECONOMICS_RECEIPT_SCHEMA)


def test_checked_in_synthetic_economics_receipt_covers_the_full_boundary() -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "fixtures"
        / "opencode_go_compaction_economics.synthetic.json"
    )
    payload, rows = load_compaction_economics_receipt(path)
    report = validate_compaction_economics(rows)

    assert payload["schema"] == COMPACTION_ECONOMICS_SCHEMA
    assert not list(
        Draft202012Validator(COMPACTION_ECONOMICS_RECEIPT_SCHEMA).iter_errors(payload)
    )
    assert [row.phase for row in rows] == [
        "pre_compact",
        "compact_turn",
        "post_compact",
        "mature_post_compact",
        "resume",
    ]
    assert [row.input_tokens for row in rows] == [72020, 70000, 70800, 70950, 71000]
    assert [row.effective_uncached_input_tokens for row in rows] == [
        620,
        5050,
        820,
        850,
        900,
    ]
    assert [row.cache_read_tokens for row in rows] == [
        71400,
        64950,
        69980,
        70100,
        70100,
    ]
    assert [row.cache_write_tokens for row in rows] == [0, 0, 0, 0, 0]
    assert [row.attempts for row in rows] == [1, 1, 1, 1, 1]
    assert [row.retries for row in rows] == [0, 0, 0, 0, 0]
    assert [row.ttft_ms for row in rows] == [300, 450, 320, 310, 305]
    assert [row.duration_ms for row in rows] == [900, 1100, 880, 870, 860]
    assert len({row.request_shape_hash for row in rows}) == 5
    assert [row.stable_prefix_hash for row in rows[-3:]] == [
        "prefix-post-v1",
        "prefix-post-v1",
        "prefix-post-v1",
    ]
    assert {row.compact_boundary_hash for row in rows} == {"boundary-v1"}
    assert report["passed"] is True
    assert all(report["invariants"].values())
    assert report["summary"]["retry_amplification"] == pytest.approx(1.0)
    serialized = json.dumps(report)
    assert "prompt" not in serialized
    assert "content" not in serialized
    assert "tool_result" not in serialized


@pytest.mark.parametrize(
    "change, failed",
    [
        (
            lambda rows: [replace(rows[0], stable_prefix_hash=None), *rows[1:]],
            "stable_prefix_hashes_present",
        ),
        (
            lambda rows: [
                *rows[:1],
                replace(rows[1], request_shape_hash=None),
                *rows[2:],
            ],
            "request_shape_hashes_present",
        ),
        (
            lambda rows: [
                *rows[:2],
                replace(rows[2], compact_boundary_hash="other"),
                *rows[3:],
            ],
            "compact_boundary_identity",
        ),
        (
            lambda rows: [
                *rows[:1],
                replace(rows[1], learning_memory_ids=("learning-memory-hash-1",)),
                *rows[2:],
            ],
            "learning_memory_not_duplicated",
        ),
        (
            lambda rows: [*rows[:2], replace(rows[2], upstream_attempts=2), *rows[3:]],
            "retry_amplification_bounded",
        ),
        (
            lambda rows: [
                *rows[:2],
                replace(rows[2], ttft_ms=900, duration_ms=100),
                *rows[3:],
            ],
            "timings_ordered_when_available",
        ),
    ],
)
def test_compaction_economics_rejects_cross_turn_regressions(change, failed) -> None:
    path = (
        Path(__file__).parents[2]
        / "smoke"
        / "fixtures"
        / "opencode_go_compaction_economics.synthetic.json"
    )
    _, rows = load_compaction_economics_receipt(path)

    report = validate_compaction_economics(change(rows))

    assert report["passed"] is False
    assert report["invariants"][failed] is False
    with pytest.raises(ValueError, match=failed):
        assert_compaction_economics(change(rows))


def test_compaction_economics_rejects_raw_prompt_or_content_fields(tmp_path) -> None:
    path = tmp_path / "receipt.json"
    payload = {
        "schema": COMPACTION_ECONOMICS_SCHEMA,
        "evidence": "synthetic-only",
        "model": "muse-spark-1.2-contributor",
        "protocol": "responses",
        "turns": [
            {
                "model": "muse-spark-1.2-contributor",
                "protocol": "responses",
                "logical_request_id": "bad",
                "phase": "pre_compact",
                "prompt": "must not be committed",
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="metadata-only"):
        load_compaction_economics_receipt(path)


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


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda rows: rows[:-1], "same number of usage rows"),
        (
            lambda rows: [replace(rows[0], phase="resume")],
            "same phase sequence",
        ),
        (
            lambda rows: [replace(rows[0], model="other-model")],
            "same model sequence",
        ),
    ],
)
def test_compare_receipts_rejects_misaligned_workloads(mutator, message) -> None:
    native = [
        replace(
            _muse(),
            phase="pre_compact",
            compact_boundary_hash="boundary-1",
        )
    ]

    with pytest.raises(ValueError, match=message):
        compare_receipts(native, mutator(native))


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


def test_checked_in_compaction_fixture_stays_within_economic_gate() -> None:
    root = Path(__file__).parents[2] / "smoke" / "fixtures"
    native_metadata, native_rows = load_receipt(
        root / "opencode_go_compaction_native.sample.jsonl"
    )
    fcc_metadata, fcc_rows = load_receipt(
        root / "opencode_go_compaction_fcc.sample.jsonl"
    )

    comparison = compare_receipts(native_rows, fcc_rows)

    assert native_metadata["evidence"] == "synthetic-only"
    assert fcc_metadata["evidence"] == "synthetic-only"
    assert comparison["estimated_cost_regression_pct"] <= 5.0
    assert comparison["cache_read_share_gap_percentage_points"] <= 3.0
    assert comparison["token_amplification"] <= 1.10
    assert comparison["retry_amplification_delta"] == pytest.approx(0.0)
    assert comparison["stable_prefix_match_rate"] == pytest.approx(1.0)
    assert set(comparison["native_by_phase"]) == {
        "compact_turn",
        "post_compact",
        "pre_compact",
        "resume",
    }
