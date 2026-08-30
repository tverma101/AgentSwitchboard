from free_claude_code.core.anthropic.usage import reconcile_input_usage


def test_reconcile_input_usage_partitions_estimate_across_cache_buckets() -> None:
    input_tokens, fields = reconcile_input_usage(
        40,
        {
            "input_tokens": 999,
            "cache_read_input_tokens": 31,
            "cache_creation_input_tokens": 3,
        },
    )

    assert input_tokens == 6
    assert fields == {
        "cache_read_input_tokens": 31,
        "cache_creation_input_tokens": 3,
    }
    assert (
        input_tokens
        + fields["cache_read_input_tokens"]
        + fields["cache_creation_input_tokens"]
        == 40
    )


def test_reconcile_input_usage_drops_cache_bucket_that_cannot_fit() -> None:
    input_tokens, fields = reconcile_input_usage(
        12,
        {
            "cache_read_input_tokens": 9,
            "cache_creation_input_tokens": 10,
        },
    )

    assert input_tokens == 3
    assert fields == {"cache_read_input_tokens": 9}
    assert input_tokens + fields["cache_read_input_tokens"] == 12


def test_reconcile_input_usage_preserves_provider_breakdown_without_estimate() -> None:
    input_tokens, fields = reconcile_input_usage(
        0,
        {
            "cache_read_input_tokens": 15,
            "cache_creation_input_tokens": 3,
        },
        fallback_input_tokens=5,
    )

    assert input_tokens == 5
    assert fields == {
        "cache_read_input_tokens": 15,
        "cache_creation_input_tokens": 3,
    }


def test_reconcile_input_usage_ignores_boolean_and_negative_fields() -> None:
    input_tokens, fields = reconcile_input_usage(
        10,
        {
            "cache_read_input_tokens": True,
            "cache_creation_input_tokens": -1,
        },
    )

    assert input_tokens == 10
    assert fields == {}
