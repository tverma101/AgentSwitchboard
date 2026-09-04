"""Tests for the pre-parse public request body safety boundary."""

import json
from collections.abc import Iterable
from typing import cast

import pytest
from starlette.types import ASGIApp, Message, Scope

from free_claude_code.api.request_body import PublicRequestBodyLimitMiddleware
from free_claude_code.api.request_ids import RequestCorrelationMiddleware
from tests.api.support import create_test_app


def _scope(path: str, *, content_length: int | None = None) -> Scope:
    headers: list[tuple[bytes, bytes]] = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    return cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": None,
            "server": None,
        },
    )


async def _run(
    app: ASGIApp,
    scope: Scope,
    incoming: Iterable[Message],
) -> list[Message]:
    messages = iter(incoming)
    sent: list[Message] = []

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


async def _consume_body(scope: Scope, receive, send) -> None:
    del scope
    while True:
        message = await receive()
        if message["type"] != "http.request" or not message.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b"", "more_body": False})


def test_application_keeps_request_correlation_outside_body_limit() -> None:
    app = create_test_app()
    middleware_classes = [middleware.cls for middleware in app.user_middleware]

    correlation_index = next(
        index
        for index, middleware_class in enumerate(middleware_classes)
        if middleware_class is RequestCorrelationMiddleware
    )
    body_limit_index = next(
        index
        for index, middleware_class in enumerate(middleware_classes)
        if middleware_class is PublicRequestBodyLimitMiddleware
    )
    assert correlation_index < body_limit_index


@pytest.mark.asyncio
async def test_content_length_over_limit_rejects_before_application_runs() -> None:
    called = False

    async def app(_scope, _receive, _send) -> None:
        nonlocal called
        called = True

    middleware = PublicRequestBodyLimitMiddleware(cast(ASGIApp, app), max_bytes=5)
    sent = await _run(
        middleware,
        _scope("/v1/messages", content_length=6),
        [],
    )

    assert called is False
    assert sent[0]["status"] == 413
    payload = json.loads(sent[-1]["body"])
    assert payload["error"]["type"] == "request_too_large"


@pytest.mark.asyncio
async def test_chunked_body_over_limit_rejects_before_json_parser_can_finish() -> None:
    middleware = PublicRequestBodyLimitMiddleware(
        cast(ASGIApp, _consume_body), max_bytes=5
    )
    sent = await _run(
        middleware,
        _scope("/v1/messages"),
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ],
    )

    assert sent[0]["status"] == 413
    payload = json.loads(sent[-1]["body"])
    assert payload["type"] == "error"
    assert payload["error"]["type"] == "request_too_large"


@pytest.mark.asyncio
async def test_responses_path_uses_openai_error_envelope() -> None:
    middleware = PublicRequestBodyLimitMiddleware(
        cast(ASGIApp, _consume_body), max_bytes=3
    )
    sent = await _run(
        middleware,
        _scope("/v1/responses", content_length=4),
        [],
    )

    assert sent[0]["status"] == 413
    payload = json.loads(sent[-1]["body"])
    assert set(payload) == {"error"}
    assert payload["error"]["type"] == "request_too_large"


@pytest.mark.asyncio
async def test_exact_body_limit_still_reaches_application() -> None:
    middleware = PublicRequestBodyLimitMiddleware(
        cast(ASGIApp, _consume_body), max_bytes=6
    )
    sent = await _run(
        middleware,
        _scope("/v1/messages/count_tokens", content_length=6),
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ],
    )

    assert sent[0]["status"] == 204


@pytest.mark.asyncio
async def test_unrelated_post_path_is_not_subject_to_model_body_limit() -> None:
    middleware = PublicRequestBodyLimitMiddleware(
        cast(ASGIApp, _consume_body), max_bytes=1
    )
    sent = await _run(
        middleware,
        _scope("/admin/api/config", content_length=3),
        [{"type": "http.request", "body": b"abc", "more_body": False}],
    )

    assert sent[0]["status"] == 204
