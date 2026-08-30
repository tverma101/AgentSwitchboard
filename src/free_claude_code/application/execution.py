"""Provider execution shared by inbound API adapters."""

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from typing import Literal

from loguru import logger

from free_claude_code.core.anthropic import (
    Message,
    SystemContent,
    Tool,
    anthropic_request_snapshot,
    get_token_count,
)
from free_claude_code.core.trace import (
    close_stream_input,
    trace_event,
    traced_async_stream,
)
from free_claude_code.usage import UsageStore, UsageStreamObserver

from .ports import ProviderResolver
from .routing import RoutedMessagesRequest
from .visual_capabilities import VisualInputReceipt

TokenCounter = Callable[
    [list[Message], str | list[SystemContent] | None, list[Tool] | None],
    int,
]
WireApi = Literal["messages", "responses"]


class ProviderExecutor:
    """Resolve a provider and execute one routed Anthropic Messages stream."""

    def __init__(
        self,
        provider_resolver: ProviderResolver,
        *,
        token_counter: TokenCounter = get_token_count,
        generation_id: int | None = None,
        log_raw_payloads: bool = False,
        usage_store: UsageStore | None = None,
    ) -> None:
        self._provider_resolver = provider_resolver
        self._token_counter = token_counter
        self._generation_id = generation_id
        self._log_raw_payloads = log_raw_payloads
        self._usage_store = usage_store

    def stream(
        self,
        routed: RoutedMessagesRequest,
        *,
        wire_api: WireApi,
        raw_log_label: str,
        raw_log_payload: object,
        request_id: str,
        visual_input: VisualInputReceipt | None = None,
    ) -> AsyncIterator[str]:
        """Preflight synchronously, then return the traced provider stream."""
        visual_input_fields = (
            {"visual_input": visual_input.as_dict()} if visual_input is not None else {}
        )
        provider = self._provider_resolver(routed.resolved.provider_id)
        provider.preflight_stream(
            routed.request,
            reasoning=routed.reasoning,
        )

        gateway_model = routed.resolved.original_model
        route_trace: dict[str, object] = {
            "stage": "routing",
            "event": "free_claude_code.api.route.resolved",
            "source": "api",
            "request_id": request_id,
            "provider_id": routed.resolved.provider_id,
            "provider_model": routed.resolved.provider_model,
            "provider_model_ref": routed.resolved.provider_model_ref,
            "gateway_model": gateway_model,
            "route_source": routed.resolved.route_source,
            "alias_applied": routed.resolved.alias_applied,
            "virtual_context_window": routed.resolved.virtual_context_window,
            "reasoning_control": routed.reasoning.control.value,
            "reasoning_effort": (
                routed.reasoning.effort.value
                if routed.reasoning.effort is not None
                else None
            ),
            "reasoning_budget_tokens": routed.reasoning.budget_tokens,
        }
        if wire_api == "responses":
            route_trace["wire_api"] = "responses"
        if self._generation_id is not None:
            route_trace["generation_id"] = self._generation_id
        route_trace.update(visual_input_fields)
        trace_event(**route_trace)

        request_snapshot = anthropic_request_snapshot(routed.request)
        request_snapshot["model"] = gateway_model
        trace_event(
            stage="ingress",
            event=(
                "free_claude_code.api.responses.request.received"
                if wire_api == "responses"
                else "free_claude_code.api.request.received"
            ),
            source="api",
            message_count=len(routed.request.messages),
            snapshot=request_snapshot,
            request_id=request_id,
            **visual_input_fields,
        )

        if self._log_raw_payloads:
            logger.debug(f"{raw_log_label} [{{}}]: {{}}", request_id, raw_log_payload)

        usage_observer = (
            UsageStreamObserver(
                self._usage_store,
                request_id=request_id,
                provider_id=routed.resolved.provider_id,
                model=gateway_model,
                wire_api=wire_api,
            )
            if self._usage_store is not None
            else None
        )

        async def provider_body() -> AsyncIterator[str]:
            provider_stream: AsyncIterator[str] | None = None
            try:
                input_tokens = await asyncio.to_thread(
                    self._token_counter,
                    routed.request.messages,
                    routed.request.system,
                    routed.request.tools,
                )
                provider_stream = provider.stream_response(
                    routed.request,
                    input_tokens=input_tokens,
                    request_id=request_id,
                    response_model=gateway_model,
                    reasoning=routed.reasoning,
                )
                async for chunk in provider_stream:
                    if usage_observer is not None:
                        usage_observer.feed(chunk)
                    yield chunk
            except BaseException as exc:
                if usage_observer is not None:
                    usage_observer.finish(exc)
                raise
            else:
                if usage_observer is not None:
                    usage_observer.finish()
            finally:
                if provider_stream is not None:
                    await close_stream_input(
                        provider_stream,
                        owner="provider_executor",
                        source="api",
                        preserved_error=sys.exception(),
                    )

        stream_trace: dict[str, object] = {
            "request_id": request_id,
            "provider_id": routed.resolved.provider_id,
            "gateway_model": gateway_model,
            "route_source": routed.resolved.route_source,
            "alias_applied": routed.resolved.alias_applied,
        }
        if self._generation_id is not None:
            stream_trace["generation_id"] = self._generation_id
        stream_trace.update(visual_input_fields)

        return traced_async_stream(
            provider_body(),
            stage="egress",
            source="api",
            complete_event=(
                "free_claude_code.api.responses.stream_completed"
                if wire_api == "responses"
                else "free_claude_code.api.response.stream_completed"
            ),
            interrupted_event=(
                "free_claude_code.api.responses.stream_interrupted"
                if wire_api == "responses"
                else "free_claude_code.api.response.stream_interrupted"
            ),
            chunk_event=None,
            extra=stream_trace,
        )
