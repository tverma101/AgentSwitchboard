"""OpenCode Go provider that respects each model's documented native protocol."""

import asyncio
import json
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
from free_claude_code.core.fault_attribution import (
    AttemptEvidence,
    FaultConfidence,
    FaultDomain,
    canonical_hash,
    classify_failure,
    stable_prefix_hash,
)
from free_claude_code.core.openai_responses import (
    ResponsesConversionError,
    ResponsesProviderStream,
    ResponsesStreamFailure,
    build_responses_provider_request,
)
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from free_claude_code.core.trace import trace_event
from free_claude_code.providers.admission import (
    ProviderAdmissionController,
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
_MUSE_MODEL = "muse-spark-1.2-contributor"


def _payload_size(payload: object) -> int:
    return len(
        json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode("utf-8")
    )


def _is_transport_error(error: BaseException) -> bool:
    return isinstance(
        error,
        (
            asyncio.TimeoutError,
            ConnectionError,
            httpx.HTTPError,
        ),
    ) and not isinstance(error, httpx.HTTPStatusError)


def _record_failure(
    evidence: AttemptEvidence,
    error: BaseException,
    *,
    bridge: bool = False,
) -> None:
    code = getattr(error, "code", None)
    error_code = code if isinstance(code, str) else None
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and 100 <= status_code <= 599:
        evidence.http_status = status_code
        error_code = f"http_{status_code}"
    invalid_tool_json = error_code == "invalid_tool_arguments"
    missing_terminal = error_code in {"missing_terminal", "missing_tool_terminal"}
    complete_tool_call = evidence.complete_tool_calls is True or (
        error_code == "missing_tool_terminal" and evidence.valid_tool_json is True
    )
    if isinstance(error, httpx.HTTPStatusError):
        error_code = f"http_{error.response.status_code}"
        evidence.http_status = error.response.status_code
    domain, confidence, codes = classify_failure(
        error_code=error_code,
        transport=_is_transport_error(error),
        bridge=bridge,
        output_committed=evidence.output_committed,
        complete_tool_call=complete_tool_call,
        invalid_tool_json=invalid_tool_json,
        missing_terminal=missing_terminal,
    )
    evidence.fault_domain = domain
    evidence.confidence = confidence
    evidence.evidence_codes.extend(
        code for code in codes if code not in evidence.evidence_codes
    )
    evidence.retry_reason = error_code or type(error).__name__


def _record_completed(evidence: AttemptEvidence) -> None:
    evidence.fault_domain = FaultDomain.UNKNOWN
    evidence.confidence = FaultConfidence.HIGH
    if "stream_completed" not in evidence.evidence_codes:
        evidence.evidence_codes.append("stream_completed")


def _trace_receipt(
    evidence: AttemptEvidence,
    *,
    outcome: str,
    error: BaseException | None = None,
) -> None:
    fields: dict[str, Any] = {"outcome": outcome, **evidence.as_dict()}
    if error is not None:
        fields["error_type"] = type(error).__name__
    trace_event(
        stage="provider",
        event="provider.fault_attribution",
        source="provider",
        **fields,
    )


def _sync_responses_evidence(
    evidence: AttemptEvidence,
    stream_view: ResponsesProviderStream,
) -> None:
    evidence.terminal_event = stream_view.terminal_event
    evidence.upstream_response_id = stream_view.upstream_response_id
    evidence.tool_call_count = stream_view.tool_call_count
    evidence.complete_tool_calls = stream_view.complete_tool_calls
    evidence.valid_tool_json = stream_view.valid_tool_json
    if stream_view.usage_input_tokens is not None:
        evidence.input_tokens = stream_view.usage_input_tokens
    evidence.cache_read_tokens = stream_view.usage_cache_read_tokens
    evidence.cache_write_tokens = stream_view.usage_cache_write_tokens
    evidence.output_tokens = stream_view.usage_output_tokens


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
        responses_kwargs: dict[str, Any] = {
            "api_key": config.api_key,
            "base_url": f"{self._base_url}/",
            "max_retries": 0,
            "timeout": timeout,
        }
        # Some provider-construction tests replace httpx.AsyncClient with a
        # mock. OpenAI validates the injected client with isinstance(), so
        # only pass the shared pool when the runtime still exposes a type.
        if isinstance(httpx.AsyncClient, type):
            responses_kwargs["http_client"] = self._native_http
        self._responses = AsyncOpenAI(**responses_kwargs)

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
        return {"Authorization": f"Bearer {self._config.api_key}"}

    @staticmethod
    def _build_responses_body(
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy,
    ) -> dict[str, Any]:
        try:
            if request.model == _MUSE_MODEL and request.tool_choice is not None:
                choice_type = request.tool_choice.get("type")
                if choice_type != "auto":
                    raise InvalidRequestError(
                        "OpenCode Go Muse Responses accepts only "
                        "tool_choice.type='auto'; named and forced tool choices "
                        "are unsupported and were rejected locally."
                    )
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
        turn_id = request_id or f"turn_{uuid.uuid4().hex}"
        try:
            body = self._build_responses_body(request, reasoning=reasoning)
        except Exception as error:
            evidence = AttemptEvidence(
                turn_id=turn_id,
                request_id=request_id,
                protocol=GoProtocol.RESPONSES.value,
                provider="OPENCODE_GO",
                model=response_model,
                attempt_number=0,
            )
            _record_failure(evidence, error, bridge=True)
            _trace_receipt(evidence, outcome="error", error=error)
            raise
        body.pop("stream", None)
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
        evidence = AttemptEvidence(
            turn_id=turn_id,
            request_id=request_id,
            protocol=GoProtocol.RESPONSES.value,
            provider="OPENCODE_GO",
            model=response_model,
            attempt_number=retry_session.attempts_started,
            input_tokens=input_tokens,
            request_shape_hash=canonical_hash(body),
            stable_prefix_hash=stable_prefix_hash(body),
            tool_schema_hash=canonical_hash(body.get("tools", [])),
        )
        upstream: Any | None = None
        receipt_emitted = False
        try:
            upstream = await self._responses.responses.create(**body, stream=True)
            for event in stream_view.start():
                yield event
            async for event in upstream:
                if not attempt.accepted:
                    await attempt.succeeded()
                payload = event.model_dump(mode="json", exclude_none=True)
                event_type = payload.get("type")
                if not isinstance(event_type, str):
                    continue
                evidence.add_event(event_type, byte_count=_payload_size(payload))
                for output in stream_view.feed(event_type, payload):
                    evidence.output_committed = True
                    yield output
            if not stream_view.completed:
                raise ResponsesStreamFailure(
                    "OpenCode Go Responses stream ended without a terminal event.",
                    code="missing_terminal",
                )
            _sync_responses_evidence(evidence, stream_view)
            _record_completed(evidence)
            trace_event(
                stage="provider",
                event="provider.response.completed",
                source="provider",
                provider="OPENCODE_GO",
                request_id=request_id,
                protocol=GoProtocol.RESPONSES.value,
            )
            _trace_receipt(evidence, outcome="completed")
            receipt_emitted = True
        except asyncio.CancelledError, GeneratorExit:
            evidence.fault_domain = FaultDomain.HARNESS_TRANSPORT
            evidence.confidence = FaultConfidence.HIGH
            evidence.evidence_codes.append("stream_cancelled")
            _sync_responses_evidence(evidence, stream_view)
            _trace_receipt(evidence, outcome="cancelled")
            receipt_emitted = True
            raise
        except Exception as error:
            _sync_responses_evidence(evidence, stream_view)
            _record_failure(evidence, error)
            _trace_receipt(evidence, outcome="error", error=error)
            receipt_emitted = True
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
            if not receipt_emitted:
                _sync_responses_evidence(evidence, stream_view)
                _record_failure(
                    evidence,
                    RuntimeError("Responses stream closed before receipt emission."),
                )
                _trace_receipt(evidence, outcome="abandoned")
            await attempt.aclose()

    async def _stream_messages(
        self,
        request: MessagesRequest,
        *,
        request_id: str | None,
    ) -> AsyncIterator[str]:
        turn_id = request_id or f"turn_{uuid.uuid4().hex}"
        try:
            body = build_native_messages_body(request)
        except Exception as error:
            evidence = AttemptEvidence(
                turn_id=turn_id,
                request_id=request_id,
                protocol=GoProtocol.MESSAGES.value,
                provider="OPENCODE_GO",
                model=request.model,
                attempt_number=0,
            )
            _record_failure(evidence, error, bridge=True)
            _trace_receipt(evidence, outcome="error", error=error)
            raise
        retry_session = self._admission.new_retry_session(request_id=request_id)
        attempt = await self._admission.open_attempt(retry_session)
        evidence = AttemptEvidence(
            turn_id=turn_id,
            request_id=request_id,
            protocol=GoProtocol.MESSAGES.value,
            provider="OPENCODE_GO",
            model=request.model,
            attempt_number=retry_session.attempts_started,
            request_shape_hash=canonical_hash(body),
            stable_prefix_hash=stable_prefix_hash(body),
            tool_schema_hash=canonical_hash(body.get("tools", [])),
        )
        response: httpx.Response | None = None
        saw_payload = False
        sse_buffer = ""
        receipt_emitted = False
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
            evidence.http_status = response.status_code
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
                sse_buffer += chunk
                if (
                    len(sse_buffer.encode("utf-8", errors="replace"))
                    > _ERROR_BODY_LIMIT
                ):
                    raise ResponsesStreamFailure(
                        "OpenCode Go Messages emitted an oversized SSE event.",
                        code="sse_event_too_large",
                    )
                frames = sse_buffer.split("\n\n")
                sse_buffer = frames.pop() or ""
                for frame in frames:
                    _record_messages_sse_frame(evidence, frame)
                if _sse_chunk_has_payload(chunk):
                    saw_payload = True
                if not attempt.accepted:
                    await attempt.succeeded()
                yield chunk
            if sse_buffer.strip():
                _record_messages_sse_frame(evidence, sse_buffer)
            if not saw_payload:
                raise ResponsesStreamFailure(
                    "OpenCode Go Messages stream ended without output.",
                    code="empty_completed_response",
                )
            if evidence.terminal_event is None:
                raise ResponsesStreamFailure(
                    "OpenCode Go Messages stream ended without a terminal event.",
                    code="missing_terminal",
                )
            evidence.output_committed = saw_payload
            _record_completed(evidence)
            trace_event(
                stage="provider",
                event="provider.response.completed",
                source="provider",
                provider="OPENCODE_GO",
                request_id=request_id,
                protocol=GoProtocol.MESSAGES.value,
            )
            _trace_receipt(evidence, outcome="completed")
            receipt_emitted = True
        except asyncio.CancelledError, GeneratorExit:
            evidence.fault_domain = FaultDomain.HARNESS_TRANSPORT
            evidence.confidence = FaultConfidence.HIGH
            evidence.evidence_codes.append("stream_cancelled")
            evidence.output_committed = saw_payload
            _trace_receipt(evidence, outcome="cancelled")
            receipt_emitted = True
            raise
        except Exception as error:
            evidence.output_committed = saw_payload
            _record_failure(evidence, error)
            _trace_receipt(evidence, outcome="error", error=error)
            receipt_emitted = True
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
            if not receipt_emitted:
                evidence.output_committed = saw_payload
                _record_failure(
                    evidence,
                    RuntimeError("Messages stream closed before receipt emission."),
                )
                _trace_receipt(evidence, outcome="abandoned")
            await attempt.aclose()


def _sse_event_types(chunk: str) -> tuple[str, ...]:
    event_types: list[str] = []
    for line in chunk.splitlines():
        stripped = line.strip()
        if stripped.startswith("event:"):
            event_type = stripped.partition(":")[2].strip()
            if event_type and event_type not in event_types:
                event_types.append(event_type)
        elif stripped.startswith("data:"):
            data = stripped.partition(":")[2].strip()
            if data == "[DONE]" and "sse.done" not in event_types:
                event_types.append("sse.done")
    if not event_types and _sse_chunk_has_payload(chunk):
        return ("sse.data",)
    return tuple(event_types)


def _record_messages_sse_frame(evidence: AttemptEvidence, frame: str) -> None:
    event_types = _sse_event_types(frame)
    for event_type in event_types:
        evidence.add_event(event_type)
    if "error" in event_types:
        raise ResponsesStreamFailure(
            "OpenCode Go Messages returned an SSE error event.",
            code="upstream_sse_error",
        )
    if "message_stop" in event_types:
        evidence.terminal_event = "message_stop"
    elif "sse.done" in event_types:
        evidence.terminal_event = "sse.done"


def _sse_chunk_has_payload(chunk: str) -> bool:
    for line in chunk.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data = stripped.partition(":")[2].strip()
        if data and data != "[DONE]":
            return True
    return False


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
