"""Usage ledger and stream-observer tests."""

import sqlite3
from datetime import datetime

from free_claude_code.core.account_identity import account_fingerprint
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


def test_usage_stream_observer_preserves_disjoint_opencode_receipt_attribution(
    tmp_path,
):
    store = UsageStore(tmp_path / "usage.db")
    observer = UsageStreamObserver(
        store,
        request_id="opencode-receipt-1",
        provider_id="opencode_go",
        model="opencode_go/muse-spark-1.2-contributor",
        wire_api="responses",
    )
    observer.feed(
        'event: message_delta\ndata: {"usage":{"input_tokens":9,'
        '"output_tokens":4,"cache_read_input_tokens":31}}\n\n'
        "event: message_stop\ndata: {}\n\n"
    )
    observer.finish()

    summary = store.summary(days=1)
    assert summary["totals"] == {
        "requests": 1,
        "successful_requests": 1,
        "failed_requests": 0,
        "input_tokens": 9,
        "output_tokens": 4,
        "cache_read_input_tokens": 31,
        "cache_creation_input_tokens": 0,
        "web_search_requests": 0,
        "web_fetch_requests": 0,
    }
    assert summary["models"] == [
        {
            "provider_id": "opencode_go",
            "model": "opencode_go/muse-spark-1.2-contributor",
            "wire_api": "responses",
            "wire_api_label": "OpenAI Responses",
            "source": "fcc_proxy",
            "source_label": "FCC proxy",
            "account_fingerprint": None,
            "account_label": "Account not identified",
            "tracking_label": "FCC proxy · OpenAI Responses · Account not identified",
            "requests": 1,
            "successful_requests": 1,
            "failed_requests": 0,
            "input_tokens": 9,
            "output_tokens": 4,
            "cache_read_input_tokens": 31,
            "cache_creation_input_tokens": 0,
        }
    ]


def test_usage_tracking_keeps_accounts_and_wire_apis_separate(tmp_path):
    store = UsageStore(tmp_path / "usage.db")
    first_account = account_fingerprint("openai", "account-one")
    second_account = account_fingerprint("openai", "account-two")
    now = datetime.now().astimezone()

    for request_id, wire_api, fingerprint in (
        ("tracking-1", "messages", first_account),
        ("tracking-2", "messages", second_account),
        ("tracking-3", "responses", first_account),
    ):
        store.record(
            UsageEvent(
                request_id=request_id,
                occurred_at=now,
                provider_id="openai",
                model="openai/gpt-5.6-luna",
                wire_api=wire_api,
                status="success",
                duration_ms=10,
                input_tokens=10,
                output_tokens=2,
                account_fingerprint=fingerprint,
            )
        )

    rows = store.summary(days=1, now=now)["models"]

    assert {
        (row["wire_api"], row["account_fingerprint"], row["requests"]) for row in rows
    } == {
        ("messages", first_account, 1),
        ("messages", second_account, 1),
        ("responses", first_account, 1),
    }
    assert all(row["source"] == "fcc_proxy" for row in rows)
    assert all("FCC proxy" in row["tracking_label"] for row in rows)


def test_usage_store_resolves_account_at_record_time_without_blocking_events(tmp_path):
    calls: list[str] = []

    def resolve(provider_id: str) -> str | None:
        calls.append(provider_id)
        return account_fingerprint("openai", "account-current")

    store = UsageStore(
        tmp_path / "usage.db",
        account_fingerprint_resolver=resolve,
    )
    now = datetime.now().astimezone()
    store.record(
        UsageEvent(
            request_id="resolver-1",
            occurred_at=now,
            provider_id="openai",
            model="openai/gpt-5.6-luna",
            wire_api="responses",
            status="success",
            duration_ms=1,
        )
    )

    row = store.summary(days=1, now=now)["models"][0]
    assert calls == ["openai"]
    assert row["account_fingerprint"] == account_fingerprint(
        "openai", "account-current"
    )


def test_usage_store_keeps_event_when_account_resolution_fails(tmp_path):
    def resolve(_provider_id: str) -> str | None:
        raise RuntimeError("account manager unavailable")

    store = UsageStore(
        tmp_path / "usage.db",
        account_fingerprint_resolver=resolve,
    )
    now = datetime.now().astimezone()
    store.record(
        UsageEvent(
            request_id="resolver-failure-1",
            occurred_at=now,
            provider_id="openai",
            model="openai/gpt-5.6-luna",
            wire_api="messages",
            status="error",
            duration_ms=1,
        )
    )

    row = store.summary(days=1, now=now)["models"][0]
    assert row["requests"] == 1
    assert row["account_fingerprint"] is None


def test_usage_store_migrates_legacy_ledger_without_rewriting_history(tmp_path):
    path = tmp_path / "usage.db"
    now = datetime.now().astimezone()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE usage_events (
                request_id TEXT PRIMARY KEY,
                occurred_at TEXT NOT NULL,
                local_day TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                model TEXT NOT NULL,
                wire_api TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
                cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
                web_search_requests INTEGER NOT NULL DEFAULT 0,
                web_fetch_requests INTEGER NOT NULL DEFAULT 0,
                error_type TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO usage_events (
                request_id, occurred_at, local_day, provider_id, model,
                wire_api, status, duration_ms, input_tokens, output_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-1",
                now.isoformat(),
                now.date().isoformat(),
                "openai",
                "openai/gpt-5.6-luna",
                "responses",
                "success",
                3,
                8,
                1,
            ),
        )

    store = UsageStore(path)
    summary = store.summary(days=1, now=now)
    row = summary["models"][0]

    assert row["source"] == "fcc_proxy"
    assert row["account_fingerprint"] is None
    assert row["tracking_label"] == (
        "FCC proxy · OpenAI Responses · Account not identified"
    )
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(usage_events)")
        }
    assert {"source", "account_fingerprint"} <= columns
