import pytest

from smoke.lib.opencode_go_transport import (
    TransportBenchmarkConfig,
    run_transport_benchmark,
)


@pytest.mark.asyncio
async def test_synthetic_transport_receipt_is_reproducible_and_metadata_only() -> None:
    receipt = await run_transport_benchmark(
        TransportBenchmarkConfig(
            mode="synthetic",
            samples=(1, 3),
            response_bytes=2048,
        )
    )

    metrics = receipt["metrics"]
    assert receipt["protocol"] == "messages"
    assert receipt["sample_counts"] == [1, 3]
    assert metrics["logical_requests"] == 3
    assert metrics["upstream_attempts"] == 3
    assert metrics["retry_amplification"] == 1.0
    assert metrics["full_success_response_buffered"] is False
    assert metrics["connection_reuse_count"] >= 1
    assert len(receipt["raw_samples"]) == 3
    assert all(
        "synthetic transport benchmark" not in sample
        for sample in receipt["raw_samples"]
    )
