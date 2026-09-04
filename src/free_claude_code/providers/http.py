"""Shared HTTP lifecycle helpers for upstream provider clients."""

import inspect
import json
from typing import Any

import httpx
from loguru import logger

from free_claude_code.core.trace import trace_event
from free_claude_code.providers.model_listing import (
    MAX_MODEL_LIST_RESPONSE_BYTES,
    ModelListResponseError,
)


async def request_model_list_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider_name: str,
    **request_kwargs: Any,
) -> Any:
    """Fetch and decode one model catalog without eagerly buffering unbounded bytes."""
    request = client.build_request(method, url, **request_kwargs)
    response = await client.send(request, stream=True)
    try:
        response.raise_for_status()
        raw_content_length = response.headers.get("content-length")
        if raw_content_length is not None:
            try:
                content_length = int(raw_content_length)
            except ValueError:
                content_length = None
            if (
                content_length is not None
                and content_length > MAX_MODEL_LIST_RESPONSE_BYTES
            ):
                raise ModelListResponseError(
                    f"{provider_name} model-list response exceeded maximum "
                    f"bytes ({MAX_MODEL_LIST_RESPONSE_BYTES})"
                )

        parts: list[bytes] = []
        received = 0
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > MAX_MODEL_LIST_RESPONSE_BYTES:
                raise ModelListResponseError(
                    f"{provider_name} model-list response exceeded maximum "
                    f"bytes ({MAX_MODEL_LIST_RESPONSE_BYTES})"
                )
            parts.append(chunk)
        try:
            return json.loads(b"".join(parts))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelListResponseError(
                f"{provider_name} model-list response is malformed: invalid JSON"
            ) from exc
    finally:
        await maybe_await_aclose(response)


async def maybe_await_aclose(response: Any) -> None:
    """Call ``aclose`` on httpx-like responses; ignore sync test doubles."""
    close = getattr(response, "aclose", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def close_provider_stream(
    stream: Any,
    *,
    active_error: BaseException | None,
    provider_name: str,
    request_id: str | None,
) -> None:
    """Close one stream without letting cleanup change its established outcome."""
    try:
        await maybe_await_aclose(stream)
    except Exception as close_error:
        active_error_type = (
            type(active_error).__name__ if active_error is not None else None
        )
        trace_event(
            stage="provider",
            event="provider.stream.close_failed",
            source="provider",
            provider=provider_name,
            request_id=request_id,
            close_exc_type=type(close_error).__name__,
            preserved_exc_type=active_error_type,
        )
        logger.warning(
            "{}_STREAM_CLOSE_FAILED request_id={} close_exc_type={} "
            "preserved_exc_type={}",
            provider_name,
            request_id,
            type(close_error).__name__,
            active_error_type,
        )
