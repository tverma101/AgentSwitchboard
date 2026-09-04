"""Bound public model request bodies before JSON/Pydantic allocation."""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from free_claude_code.core.anthropic import anthropic_error_payload
from free_claude_code.core.openai_responses import openai_error_payload

MAX_PUBLIC_REQUEST_BODY_BYTES = 64 * 1024 * 1024
_LIMITED_PATHS = frozenset(
    {
        "/v1/messages",
        "/v1/messages/count_tokens",
        "/v1/responses",
    }
)


class _RequestBodyTooLarge(Exception):
    """Internal control-flow signal raised before an oversized body is parsed."""


class PublicRequestBodyLimitMiddleware:
    """Reject oversized public model requests while their ASGI body is streaming."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int = MAX_PUBLIC_REQUEST_BODY_BYTES,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("request body limit must be positive")
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") not in _LIMITED_PATHS
        ):
            await self._app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self._max_bytes:
            await self._reject(scope, send)
            return

        total_bytes = 0

        async def limited_receive() -> Message:
            nonlocal total_bytes
            message = await receive()
            if message["type"] == "http.request":
                total_bytes += len(message.get("body", b""))
                if total_bytes > self._max_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self._app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        message = (
            "request body exceeds the FCC ingress safety limit "
            f"({self._max_bytes} bytes)"
        )
        if scope.get("path") == "/v1/responses":
            payload = openai_error_payload(
                message=message,
                error_type="request_too_large",
            )
        else:
            payload = anthropic_error_payload(
                error_type="request_too_large",
                message=message,
            )
        response = JSONResponse(status_code=413, content=payload)
        await response(scope, _empty_receive, send)


def _content_length(scope: Scope) -> int | None:
    raw = Headers(scope=scope).get("content-length")
    if raw is None:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


__all__ = ["MAX_PUBLIC_REQUEST_BODY_BYTES", "PublicRequestBodyLimitMiddleware"]
