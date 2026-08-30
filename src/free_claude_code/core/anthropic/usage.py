"""Shared Anthropic usage-accounting helpers."""

from collections.abc import Mapping


def reconcile_input_usage(
    estimated_input_tokens: int,
    usage_fields: Mapping[str, int],
    *,
    fallback_input_tokens: int | None = None,
) -> tuple[int, dict[str, int]]:
    """Return a client-facing input usage partition.

    Claude Code calculates context usage from the sum of ``input_tokens``,
    ``cache_read_input_tokens``, and ``cache_creation_input_tokens``. Provider
    counters can use a different denominator or report an impossible cache
    breakdown, so a provider receipt must not publish those values
    independently of FCC's governed request estimate.

    When an estimate is available, it is the source of truth. Cache buckets
    are retained in a stable order only while they fit in the remaining
    estimate; the ordinary input bucket receives the remainder. When a caller
    has no estimate (``<= 0``), preserve the provider-derived breakdown and
    use the optional fallback for the ordinary input bucket.
    """
    fields = {
        key: value
        for key, value in usage_fields.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    if estimated_input_tokens <= 0:
        input_tokens = fields.get("input_tokens")
        if input_tokens is None or input_tokens < 0:
            input_tokens = fallback_input_tokens
        return max(0, input_tokens or 0), fields

    client_input_tokens = max(0, estimated_input_tokens)
    fields.pop("input_tokens", None)
    for field_name in (
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        cache_tokens = fields.get(field_name)
        if cache_tokens is None:
            continue
        if 0 <= cache_tokens <= client_input_tokens:
            client_input_tokens -= cache_tokens
        else:
            # Publishing a bucket larger than the remaining estimate makes
            # Claude's statusline jump beyond the count_tokens result.
            fields.pop(field_name, None)
    return client_input_tokens, fields
