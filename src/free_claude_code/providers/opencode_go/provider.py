"""OpenCode Go provider that respects each model's documented native protocol."""

import asyncio
import sys
import uuid
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

import httpx
from openai import AsyncOpenAI

from free_claude_code.application.errors import InvalidRequestError
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.anthropic.openai_tool_names import OpenAIToolNameCodec
from free_claude_code.core.failures import ExecutionFailure
from free_claude_code.core.openai_responses import (
    ResponsesConversionError,
    ResponsesProviderStream,
    build_responses_provider_request,
)
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from free_claude_code.core.trace import trace_event
from free_claude_code.providers.admission import (
    ProviderAdmissionController,
    ProviderAttempt,
)
from free_claude_code.providers.base import BaseProvider, ProviderConfig
from free_claude_code.providers.failure_policy import classify_provider_failure
from free_claude_code.providers.http import close_provider_stream
from free_claude_code.providers.model_listing import extract_openai_model_infos
from free_claude_code.providers.openai_chat import (
    OPENAI_CHAT_PROFILES,
    OpenAIChatProvider,
)

_GO_DOCS_SOURCE = "https://dev.opencode.ai/docs/go/"
_GO_DOCS_DATE = "2026-08-23"
_ERROR_BODY_LIMIT = 65_536


class GoProtocol(StrEnum):
    """Wire protocols currently documented by OpenCode Go."""

    CHAT = "chat/completions"
    RESPONSES = "responses"
    MESSAGES = "messages"


GO_MODEL_PROTOCOLS: dict[str, GoProtocol] = {
    "grok-4.5": GoProtocol.RESPONSES,
    "gpt-5.6-luna": GoProtocol.RESPONSES,
    "glm-5.3": GoProtocol.CHAT,
    "glm-5.2": GoProtocol.CHAT,
    "glm-5.1": GoProtocol.CHAT,
    "kimi-k3": GoProtocol.CHAT,
    "kimi-k2.7-code": GoProtocol.CHAT,
    "kimi-k2.6": GoProtocol.CHAT,
    "deepseek-v4-pro": GoProtocol.CHAT,
    "deepseek-v4-flash": GoProtocol.CHAT,
    "deepseek-v4-flash-vision-exp": GoProtocol.CHAT,
    "mimo-v2.5": GoProtocol.CHAT,
    "mimo-v2.5-pro": GoProtocol.CHAT,
    "minimax-m3": GoProtocol.MESSAGES,
    "minimax-m2.7": GoProtocol.MESSAGES,
    "minimax-m2.5": GoProtocol.MESSAGES,
    "muse-spark-1.2-contributor": GoProtocol.RESPONSES,
    "qwen3.8-max": GoProtocol.MESSAGES,
    "qwen3.7-max": GoProtocol.MESSAGES,
    "qwen3.7-plus": GoProtocol.MESSAGES,
    "qwen3.6-plus": GoProtocol.MESSAGES,
    "hy3": GoProtocol.CHAT,
    "ox-alpha-free": GoProtocol.CHAT,
}


def protocol_for_model(model_id: str) -> GoProtocol:
    """Return the documented Go protocol, failing closed for unknown models."""

    try:
        return GO_MODEL_PROTOCOLS[model_id]
    except KeyError as exc:
        raise InvalidRequestError(
            "OpenCode Go model protocol is unknown for "
            f"{model_id!r}. Update the protocol manifest from {_GO_DOCS_SOURCE} "
            f"(current manifest {_GO_DOCS_DATE}) instead of probing billable endpoints."
        ) from exc


def build_native_messages_body(request: MessagesRequest) -> dict[str, Any]:
    """Serialize an Anthropic-native Go request without cross-protocol fields."""

    if request.extra_body:
        raise InvalidRequestError(
            "OpenCode Go native Messages requests do not accept FCC extra_body."
        )
    body = request.model_dump(mode="json", exclude_none=True)
    body["stream"] = True
    return body


class OpenCodeGoProvider(BaseProvider):
    """Route Go models to Chat Completions, Responses, or Messages natively."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        admission: ProviderAdmissionController,
    ) -> None:
        super().__init__(config)
        self._admission = admission
        self._base_url = config.base_url.rstrip("/")
        self._chat = OpenAIChatProvider(
            config,
            profile=OPENAI_CHAT_PROFILES["opencode_go"],
            admission=admission,
        )
        timeout = httpx.Timeout(
            config.http_read_timeout,
            connect=config.http_connect_timeout,
            read=config.http_read_timeout,
            write=config.http_write_timeout,
        )
        max_connections = max(4, config.max_concurrency * 2)
        self._native_http = httpx.AsyncClient(
            proxy=config.proxy or None,
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max(2, config.max_concurrency),
                keepalive_expiry=30.0,
            ),
        )
        self._responses = AsyncOpenAI(
            api_key=config.api_key,
            base_url=f"{self._base_url}/",
            max_retries=0,
            timeout=timeout,
            http_client=self._native_http,
            default_headers={"x-api-key": config.api_key},
        )

    def preflight_stream(
        self,
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> None:
        """Validate conversion for the model's documented Go wire protocol."""

        protocol = protocol_for_model(request.model)
        if protocol is GoProtocol.CHAT:
            self._chat.preflight_stream(request, reasoning=reasoning)
            return
        if protocol is GoProtocol.MESSAGES:
            build_native_messages_body(request)
            return
        self._build_responses_body(request, reasoning=reasoning)

    async def cleanup(self) -> None:
        """Close both long-lived protocol transport pools."""

        await self._chat.cleanup()
        await self._responses.close()

    async def list_model_infos(self) -> frozenset[ProviderModelInfo]:
        """Fetch Go's model catalog through the hardened native transport."""

        async def fetch() -> Any:
            response = await self._native_http.get(
                f"{self._base_url}/models",
                headers=self._auth_headers(),
            )
            response.raise_for_status()
            return response.json()

        payload = await self._admission.run_with_retry(fetch)
        return extract_openai_model_infos(payload, provider_name="OPENCODE_GO")

    def stream_response(
        self,
        request: MessagesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> AsyncIterator[str]:
        """Route one request exactly once to the documented Go protocol."""

        protocol = protocol_for_model(request.model)
        if protocol is GoProtocol.CHAT:
            return self._chat.stream_response(
                request,
                input_tokens,
                request_id=request_id,
                response_model=response_model,
                reasoning=reasoning,
            )
        if protocol is GoProtocol.MESSAGES:
            return self._stream_messages(
                request,
                request_id=request_id,
            )
        return self._stream_responses(
            request,
            input_tokens=input_tokens,
            request_id=request_id,
            response_model=response_model or request.model,
            reasoning=reasoning,
        )

    def _auth_headers(self) -> dict[str, str]:
        key = self._config.api_key
        return {
            "Authorization": f"Bearer {key}",
            "x-api-key": key,
        }

    @staticmethod
    def _build_responses_body(
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy,
    ) -> dict[str, Any]:
        try:
            return build_responses_provider_request(request, reasoning=reasoning)
        except ResponsesConversionError as exc:
            raise InvalidRequestError(str(exc)) from exc

    async def _stream_responses(
        self,
        request: MessagesRequest,
        *,
        input_tokens: int,
        request_id: str | None,
        response_model: str,
        reasoning: ReasoningPolicy,
    ) -> AsyncIterator[str]:
        body = self._build_responses_body(request, reasoning=reasoning)
        tool_names = OpenAIToolNameCodec.from_request(request)
        stream_view = ResponsesProviderStream(
            message_id=f"msg_{uuid.uuid4()}",
            model=response_model,
            input_tokens=input_tokens,
            log_raw_events=self._config.log_raw_sse_events,
            tool_names=tool_names,
        )
        retry_session = self._admission.new_retry_session(request_id=request_id)
        attempt = await self._admission.open_attempt(retry_session)
        upstream: Any | None = None
        try:
            upstream = await self._responses.responses.create(**body)
            for event in stream_view.start():
                yield event
            async for event in upstream:
                if not attempt.accepted:
                    await attempt.succeeded()
                payload = event.model_dump(mode="json", exclude_none=True)
                event_type = payload.get("type")
                if not isinstance(event_type, str):
                    continue
                for output in stream_view.feed(event_type, payload):
                    yield output
            if not stream_view.completed:
                raise RuntimeError(
                    "OpenCode Go Responses stream ended without a terminal event."
                )
            trace_event(
                stage="provider",
                event="provider.response.completed",
                source="provider",
                provider="OPENCODE_GO",
                request_id=request_id,
                protocol=GoProtocol.RESPONSES.value,
            )
        except asyncio.CancelledError, GeneratorExit:
            raise
        except Exception as error:
            self._log_stream_transport_error(
                "OPENCODE_GO",
                f" request_id={request_id}" if request_id else "",
                error,
                request_id=request_id,
            )
            raise classify_provider_failure(
                error,
                provider_name="OpenCode Go",
                read_timeout_s=self._config.http_read_timeout,
                request_id=request_id,
            ) from error
        finally:
            if upstream is not None:
                await close_provider_stream(
                    upstream,
                    active_error=sys.exception(),
                    provider_name="OPENCODE_GO",
                    request_id=request_id,
                )
            await attempt.aclose()

    async def _stream_messages(
        self,
        request: MessagesRequest,
        *,
        request_id: str | None,
    ) -> AsyncIterator[str]:
        body = build_native_messages_body(request)
        retry_session = self._admission.new_retry_session(request_id=request_id)
        attempt = await self._admission.open_attempt(retry_session)
        response: httpx.Response | None = None
        try:
            response = await self._native_http.send(
                self._native_http.build_request(
                    "POST",
                    f"{self._base_url}/messages",
                    json=body,
                    headers={
                        **self._auth_headers(),
                        "anthropic-version": "2023-06-01",
                        "accept": "text/event-stream",
                    },
                ),
                stream=True,
            )
            if not response.is_success:
                detail = await _bounded_error_text(response)
                error = httpx.HTTPStatusError(
                    f"OpenCode Go Messages error: {detail}",
                    request=response.request,
                    response=response,
                )
                raise error
            content_type = response.headers.get("content-type", "")
            if content_type and "text/event-stream" not in content_type.lower():
                raise RuntimeError(
                    "OpenCode Go Messages returned a non-SSE success response."
                )
            async for chunk in response.aiter_text():
                if not chunk:
                    continue
                if not attempt.accepted:
                    await attempt.succeeded()
                yield chunk
            trace_event(
                stage="provider",
                event="provider.response.completed",
                source="provider",
                provider="OPENCODE_GO",
                request_id=request_id,
                protocol=GoProtocol.MESSAGES.value,
            )
        except asyncio.CancelledError, GeneratorExit:
            raise
        except Exception as error:
            self._log_stream_transport_error(
                "OPENCODE_GO",
                f" request_id={request_id}" if request_id else "",
                error,
                request_id=request_id,
            )
            failure: ExecutionFailure = classify_provider_failure(
                error,
                provider_name="OpenCode Go",
                read_timeout_s=self._config.http_read_timeout,
                request_id=request_id,
            )
            raise failure from error
        finally:
            if response is not None:
                await response.aclose()
            await attempt.aclose()


async def _bounded_error_text(response: httpx.Response) -> str:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        remaining = _ERROR_BODY_LIMIT + 1 - len(body)
        if remaining <= 0:
            break
        body.extend(chunk[:remaining])
        if len(body) > _ERROR_BODY_LIMIT:
            break
    suffix = "…" if len(body) > _ERROR_BODY_LIMIT else ""
    return body[:_ERROR_BODY_LIMIT].decode("utf-8", errors="replace") + suffix
