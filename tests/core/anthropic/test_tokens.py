"""Regression tests for stable Anthropic token estimates."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from typing import cast

import free_claude_code.core.anthropic.tokens as token_module
from free_claude_code.core.anthropic.models import (
    ContentBlockToolResult,
    Message,
    Tool,
)


def test_tool_search_controller_definitions_are_not_counted_as_provider_tools() -> None:
    message = Message(role="user", content="find the value")
    ordinary_tool = Tool(
        name="lookup",
        description="Look up a value",
        input_schema={"type": "object", "properties": {}},
    )
    controller = Tool(
        name="tool_search_tool_regex",
        type="tool_search_tool_regex_20251119",
        input_schema={"type": "object", "properties": {}},
    )

    with_controller = token_module.get_token_count(
        [message], tools=[ordinary_tool, controller]
    )
    without_controller = token_module.get_token_count([message], tools=[ordinary_tool])

    assert with_controller == without_controller


def test_tool_schema_key_order_does_not_change_the_estimate() -> None:
    message = Message(role="user", content="use the tool")
    first_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    }
    reordered_schema = {
        "required": ["query"],
        "properties": {
            "limit": {"type": "integer"},
            "query": {"type": "string"},
        },
        "type": "object",
    }

    first = token_module.get_token_count(
        [message], tools=[Tool(name="lookup", input_schema=first_schema)]
    )
    reordered = token_module.get_token_count(
        [message], tools=[Tool(name="lookup", input_schema=reordered_schema)]
    )

    assert reordered == first


def test_image_inside_tool_result_is_counted_as_media_not_base64_text() -> None:
    small_image = Message(
        role="user",
        content=[
            ContentBlockToolResult(
                type="tool_result",
                tool_use_id="call_small",
                content=[
                    {
                        "type": "image",
                        "mimeType": "image/png",
                        "data": "x" * 3_000,
                    }
                ],
            )
        ],
    )
    large_image = Message(
        role="user",
        content=[
            ContentBlockToolResult(
                type="tool_result",
                tool_use_id="call_large",
                content=[
                    {
                        "type": "image",
                        "mimeType": "image/png",
                        "data": "x" * 900_000,
                    }
                ],
            )
        ],
    )

    small_count = token_module.get_token_count([small_image])
    large_count = token_module.get_token_count([large_image])

    assert large_count > small_count
    assert large_count - small_count <= 300


def test_media_cache_key_does_not_retain_base64_payload() -> None:
    canonical = token_module._canonical_value(
        {"type": "image", "mimeType": "image/png", "data": "x" * 900_000}
    )

    assert isinstance(canonical, dict)
    canonical_mapping = cast(dict[str, object], canonical)
    payload = canonical_mapping["data"]
    assert isinstance(payload, dict)
    payload_mapping = cast(dict[str, object], payload)
    assert payload_mapping["length"] == 900_000
    assert payload_mapping["sha256"] != "x" * 64


def test_concurrent_duplicate_counts_share_one_calculation(monkeypatch) -> None:
    token_module._TOKEN_COUNT_MEMO.clear()
    original = token_module._count_token_request
    started = Event()
    release = Event()
    calls = 0

    def counted_once(messages, system, tools):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return original(messages, system, tools)

    monkeypatch.setattr(token_module, "_count_token_request", counted_once)
    message = Message(
        role="user",
        content="unique concurrent count probe 7f6f1c8b",
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(token_module.get_token_count, [message]) for _ in range(4)
        ]
        try:
            assert started.wait(timeout=2)
        finally:
            release.set()
        results = [future.result(timeout=2) for future in futures]

    assert len(set(results)) == 1
    assert calls == 1


def test_distinct_count_probes_are_concurrency_bounded(monkeypatch) -> None:
    token_module._TOKEN_COUNT_MEMO.clear()
    original = token_module._count_token_request
    first_two_started = Event()
    release = Event()
    lock = Lock()
    active = 0
    maximum_active = 0
    calls = 0

    def bounded_count(messages, system, tools):
        nonlocal active, maximum_active, calls
        with lock:
            active += 1
            calls += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                first_two_started.set()
        release.wait(timeout=2)
        with lock:
            active -= 1
        return original(messages, system, tools)

    monkeypatch.setattr(token_module, "_count_token_request", bounded_count)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(
                token_module.get_token_count,
                [Message(role="user", content=f"distinct probe {index}")],
            )
            for index in range(4)
        ]
        assert first_two_started.wait(timeout=2)
        with lock:
            assert calls == 2
            assert maximum_active == 2
        release.set()
        results = [future.result(timeout=2) for future in futures]

    assert len(set(results)) == 1
