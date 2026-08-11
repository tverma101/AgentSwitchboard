"""Usage ledger and stream-observer tests."""

from datetime import datetime

from free_claude_code.usage import UsageEvent, UsageStore, UsageStreamObserver


def test_usage_store_returns_reconciled_daily_and_model_buckets(tmp_path):
    local_tz = datetime.now().astimezone().tzinfo
    now = datetime(2026, 8, 10, 12, tzinfo=local_tz)
    store = UsageStore(tmp_path / "usage.db")
    store.record(
        UsageEvent(
            request_id="success-1",
            occurred_at=now,
            provider_id="opencode_zen",
            model="opencode_zen/deepseek-v4-flash-free",
            wire_api="messages",
            status="success",
            duration_ms=120,
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=50,
            web_search_requests=2,
        )
    )
    store.record(
        UsageEvent(
            request_id="error-1",
            occurred_at=now.replace(day=9),
            provider_id="opencode_go",
            model="opencode_go/deepseek-v4-flash",
            wire_api="responses",
            status="error",
            duration_ms=80,
            input_tokens=7,
            error_type="UpstreamError",
        )
    )

    summary = store.summary(days=3, now=now)

    assert summary["from"] == "2026-08-08"
    assert summary["to"] == "2026-08-10"
    assert summary["totals"] == {
        "requests": 2,
        "successful_requests": 1,
        "failed_requests": 1,
        "input_tokens": 107,
        "output_tokens": 20,
        "cache_read_input_tokens": 50,
        "cache_creation_input_tokens": 0,
        "web_search_requests": 2,
        "web_fetch_requests": 0,
    }
    assert [day["requests"] for day in summary["daily"]] == [0, 1, 1]
    assert summary["models"][0]["model"] == "opencode_zen/deepseek-v4-flash-free"
    assert summary["models"][1]["failed_requests"] == 1


def test_usage_stream_observer_handles_split_sse_and_only_records_counters(tmp_path):
    store = UsageStore(tmp_path / "usage.db")
    observer = UsageStreamObserver(
        store,
        request_id="stream-1",
        provider_id="opencode_go",
        model="opencode_go/deepseek-v4-flash",
        wire_api="messages",
    )
    payload = (
        'event: message_start\ndata: {"type":"message_start",'
        '"message":{"usage":{"input_tokens":12}}}\n\n'
        'event: message_delta\ndata: {"type":"message_delta",'
        '"usage":{"input_tokens":15,"output_tokens":7,'
        '"cache_read_input_tokens":3,"cache_creation_input_tokens":2,'
        '"server_tool_use":{"web_search_requests":1,'
        '"web_fetch_requests":2}}}\n\n'
        'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )
    observer.feed(payload[:83])
    observer.feed(payload[83:])
    observer.finish()

    totals = store.summary(days=1)["totals"]
    assert totals == {
        "requests": 1,
        "successful_requests": 1,
        "failed_requests": 0,
        "input_tokens": 15,
        "output_tokens": 7,
        "cache_read_input_tokens": 3,
        "cache_creation_input_tokens": 2,
        "web_search_requests": 1,
        "web_fetch_requests": 2,
    }
