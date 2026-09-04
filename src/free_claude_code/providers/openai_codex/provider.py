"""ChatGPT Codex backend provider using OpenAI Responses."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx

from free_claude_code.application.errors import InvalidRequestError
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.anthropic.openai_tool_names import OpenAIToolNameCodec
from free_claude_code.core.diagnostics import (
    ERROR_DETAIL_DISPLAY_CAP_BYTES,
    attach_upstream_error_body,
    extract_upstream_error_detail,
)
from free_claude_code.core.failures import ExecutionFailure, FailureKind
from free_claude_code.core.openai_responses import (
    CODEX_INSTALLATION_ID_HEADER,
    CODEX_RESPONSES_LITE_HEADER,
    CODEX_TURN_STATE_HEADER,
    CodexModelProfile,
    ResponsesConversionError,
    ResponsesProviderStream,
    ResponsesStreamFailure,
    build_responses_lite_provider_request,
    build_responses_provider_request,
    codex_client_metadata,
    codex_compatibility_headers,
    codex_model_profile,
    codex_session_headers,
    load_or_create_installation_id,
)
from free_claude_code.core.reasoning import (
    DEFAULT_REASONING_POLICY,
    ReasoningPolicy,
)
from free_claude_code.core.trace import trace_event
from free_claude_code.providers.admission import (
    ProviderAdmissionController,
    ProviderAttempt,
)
from free_claude_code.providers.base import BaseProvider, ProviderConfig
from free_claude_code.providers.failure_policy import (
    RetryableProviderProtocolError,
    classify_provider_failure,
)
from free_claude_code.providers.stream_recovery import (
    RecoveryController,
    RecoveryStreamSignal,
)

from .auth import OpenAIAccess, OpenAIAuthManager, OpenAIReconnectRequired
from .login import OPENAI_CODEX_ORIGINATOR

_MAX_CODEX_METADATA_IDENTIFIER_LENGTH = 256

try:
    FCC_VERSION = version("free-claude-code")
except PackageNotFoundError:
    FCC_VERSION = "dev"


class _TruncatedResponsesStream(RetryableProviderProtocolError):
    """A Responses stream ended without a terminal lifecycle event."""


class OpenAICodexProvider(BaseProvider):
    """Use a ChatGPT subscription through OpenAI's Codex backend."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        auth: OpenAIAuthManager,
        admission: ProviderAdmissionController,
        client: httpx.AsyncClient | None = None,
        supports_explicit_prompt_cache_breakpoints: bool = False,
        responses_lite_enabled: bool = False,
        installation_id: str | None = None,
    ) -> None:
        super().__init__(config)
        self._auth = auth
        self._admission = admission
        # This is an adapter capability, not a model-name heuristic. It is
        # injectable so a compatible backend can opt into the field after it is
        # verified to accept the GPT-5.6 request shape. The private Codex
        # endpoint currently defaults to the conservative disabled path.
        self._supports_explicit_prompt_cache_breakpoints = (
            supports_explicit_prompt_cache_breakpoints
        )
        # This capability is deliberately injected by the composition root so
        # the experimental dialect can be confined to the sandbox server.
        self._responses_lite_enabled = responses_lite_enabled
        # Native Codex keeps one installation id per machine. Minting a fresh
        # UUID per provider instance broke session affinity on every config
        # reload; persist one opaque id per FCC_CONFIG_DIR instead. Tests may
        # inject a fixed id for determinism.
        self._codex_installation_id = (
            installation_id or load_or_create_installation_id()
        )
        self._client_headers = {
            "User-Agent": f"{OPENAI_CODEX_ORIGINATOR}/{FCC_VERSION}",
            "originator": OPENAI_CODEX_ORIGINATOR,
            "version": FCC_VERSION,
        }
        self._client = client or httpx.AsyncClient(
            base_url=f"{config.base_url.rstrip('/')}/",
            proxy=config.proxy or None,
            timeout=httpx.Timeout(
                config.http_read_timeout,
                connect=config.http_connect_timeout,
                write=config.http_write_timeout,
            ),
            headers=self._client_headers,
        )
        self._owns_client = client is None

    def preflight_stream(
        self,
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> None:
        """Validate and adapt the private Codex request before upstream I/O."""

        self._build_body(request, reasoning=reasoning)

    async def cleanup(self) -> None:
        """Close only provider-owned transport resources."""

        if self._owns_client:
            await self._client.aclose()

    async def list_model_infos(self) -> frozenset[ProviderModelInfo]:
        """Discover models visible to the currently connected ChatGPT account."""

        self._authorize_egress(self._config.base_url)

        async def fetch() -> Any:
            access = await self._auth.access()
            response = await self._client.get(
                "models",
                params={"client_version": FCC_VERSION},
                headers={**self._client_headers, **_auth_headers(access)},
            )
            if response.status_code == 401:
                access = await self._auth.recover_unauthorized(access.access_token)
                response = await self._client.get(
                    "models",
                    params={"client_version": FCC_VERSION},
                    headers={**self._client_headers, **_auth_headers(access)},
                )
            response.raise_for_status()
            return response.json()

        payload = await self._admission.run_with_retry(fetch)
        return _model_infos(payload)

    def stream_response(
        self,
        request: MessagesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> AsyncIterator[str]:
        """Stream Responses output in Anthropic Messages format."""

        tool_names = OpenAIToolNameCodec.from_request(request)
        profile = self._profile_for_model(request.model)
        # Thread scope namespaces Lite prompt-only item IDs like native
        # Uuid::new_v5 under the session thread. When a Claude session id is
        # present it is known before the body is built; otherwise IDs use an
        # empty scope (no affinity exists for session-less requests anyway).
        thread_scope = (
            request.claude_session_id.strip()
            if isinstance(request.claude_session_id, str)
            and request.claude_session_id.strip()
            and len(request.claude_session_id.strip())
            <= _MAX_CODEX_METADATA_IDENTIFIER_LENGTH
            and all(
                0x21 <= ord(character) <= 0x7E
                for character in request.claude_session_id.strip()
            )
            else ""
        )
        body = self._build_body(request, reasoning=reasoning, thread_id=thread_scope)
        cache_session_id = body.get("prompt_cache_key")
        session_id = (
            cache_session_id
            if isinstance(cache_session_id, str) and cache_session_id
            else str(uuid.uuid4())
        )
        thread_id: str | None = None
        if profile is not None:
            thread_id = _safe_metadata_identifier(
                request.claude_session_id,
                fallback=session_id,
            )
            turn_id = _safe_metadata_identifier(request_id, fallback=str(uuid.uuid4()))
            body["client_metadata"] = codex_client_metadata(
                installation_id=self._codex_installation_id,
                session_id=session_id,
                thread_id=thread_id,
                turn_id=turn_id,
                window_id=f"{thread_id}:0",
            )
        return self._run_stream(
            body,
            input_tokens=input_tokens,
            request_id=request_id,
            response_model=response_model or request.model,
            tool_names=tool_names,
            reasoning=reasoning,
            session_id=session_id,
            thread_id=thread_id,
            responses_lite=profile is not None,
        )

    def _build_body(
        self,
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        profile = self._profile_for_model(request.model)
        try:
            if profile is not None:
                body = build_responses_lite_provider_request(
                    request,
                    reasoning=reasoning,
                    profile=profile,
                    thread_id=thread_id,
                )
            else:
                body = build_responses_provider_request(
                    request,
                    reasoning=reasoning,
                    explicit_prompt_cache_breakpoint=(
                        self._supports_explicit_prompt_cache_breakpoints
                    ),
                )
        except ResponsesConversionError as exc:
            raise InvalidRequestError(str(exc)) from exc
        # The private Codex backend rejects these public Responses fields.
        # Codex itself omits the output cap and uses separate internal metadata.
        body.pop("max_output_tokens", None)
        body.pop("metadata", None)
        return body

    def _profile_for_model(self, model_id: str) -> CodexModelProfile | None:
        if not self._responses_lite_enabled:
            return None
        return codex_model_profile(model_id)

    async def _run_stream(
        self,
        body: dict[str, Any],
        *,
        input_tokens: int,
        request_id: str | None,
        response_model: str,
        tool_names: OpenAIToolNameCodec,
        reasoning: ReasoningPolicy,
        session_id: str | None,
        thread_id: str | None,
        responses_lite: bool,
    ) -> AsyncIterator[str]:
        self._authorize_egress(self._config.base_url)
        retry_session = self._admission.new_retry_session(request_id=request_id)
        recovery = RecoveryController()
        message_id = f"msg_{uuid.uuid4()}"
        session_id = session_id or str(uuid.uuid4())
        # Native sticky routing replays x-codex-turn-state only within one
        # turn for retries/continuations, never across turns. Keep it local
        # to this stream call so concurrent turns cannot share routing state.
        turn_state: str | None = None
        authentication_recovered = False
        prompt_cache_breakpoint_fallback_used = False
        trace_event(
            stage="provider",
            event="provider.request.sent",
            source="provider",
            provider="openai",
            request_id=request_id,
            gateway_model=response_model,
            downstream_model=body.get("model"),
            item_count=len(body.get("input", [])),
            tool_count=_wire_tool_count(body),
        )

        while retry_session.can_attempt:
            stream = ResponsesProviderStream(
                message_id=message_id,
                model=response_model,
                input_tokens=input_tokens,
                log_raw_events=self._config.log_raw_sse_events,
                tool_names=tool_names,
                reasoning=reasoning,
            )
            for event in stream.start():
                for held in recovery.push(event):
                    yield held

            response: httpx.Response | None = None
            attempt: ProviderAttempt | None = None
            stream_opened = False
            try:
                access = await self._auth.access()
                attempt = await self._admission.open_attempt(retry_session)
                request_headers = {
                    **self._client_headers,
                    **_auth_headers(access),
                    "Accept": "text/event-stream",
                    **codex_session_headers(
                        session_id=session_id,
                        thread_id=thread_id or session_id,
                    ),
                    # Historical underscore alias retained for backend
                    # compatibility; the dashed session-id/thread-id pair is
                    # the canonical native contract.
                    "session_id": session_id,
                }
                if responses_lite:
                    request_headers.update(
                        _responses_lite_transport_headers(
                            body,
                            installation_id=self._codex_installation_id,
                        )
                    )
                if turn_state is not None:
                    request_headers[CODEX_TURN_STATE_HEADER] = turn_state
                response = await self._client.send(
                    self._client.build_request(
                        "POST",
                        "responses",
                        json=body,
                        headers=request_headers,
                    ),
                    stream=True,
                )
                incoming_turn_state = response.headers.get(CODEX_TURN_STATE_HEADER)
                if isinstance(incoming_turn_state, str) and incoming_turn_state.strip():
                    candidate = incoming_turn_state.strip()
                    if len(candidate) <= _MAX_CODEX_METADATA_IDENTIFIER_LENGTH and all(
                        0x21 <= ord(character) <= 0x7E for character in candidate
                    ):
                        turn_state = candidate
                if response.status_code == 401 and not authentication_recovered:
                    await _read_bounded_body(response)
                    await self._auth.recover_unauthorized(access.access_token)
                    await attempt.retry_immediately()
                    authentication_recovered = True
                    recovery.discard()
                    continue
                if not response.is_success:
                    body_bytes, body_truncated = await _read_bounded_body(response)
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        attach_upstream_error_body(
                            exc,
                            body_bytes,
                            truncated=body_truncated,
                        )
                        raise
                content_type = response.headers.get("content-type")
                if content_type and "text/event-stream" not in content_type.lower():
                    body_bytes, body_truncated = await _read_bounded_body(response)
                    error = _TruncatedResponsesStream(
                        "OpenAI returned a non-streaming Responses payload."
                    )
                    attach_upstream_error_body(
                        error,
                        body_bytes,
                        truncated=body_truncated,
                    )
                    raise error
                stream_opened = True
                recovery.restart_holdback_deadline()

                async for item in recovery.iterate_with_holdback_deadline(
                    _iter_sse(response)
                ):
                    if item is RecoveryStreamSignal.HOLDBACK_DEADLINE:
                        for held in recovery.flush():
                            yield held
                        continue
                    event_type, payload = item
                    if not attempt.accepted:
                        await attempt.succeeded()
                    for event in stream.feed(event_type, payload):
                        for held in recovery.push(event):
                            yield held
                if not stream.completed:
                    raise _TruncatedResponsesStream(
                        "OpenAI Responses stream ended without a terminal event."
                    )
                for event in recovery.flush():
                    yield event
                trace_event(
                    stage="provider",
                    event="provider.response.completed",
                    source="provider",
                    provider="openai",
                    request_id=request_id,
                )
                return
            except asyncio.CancelledError, GeneratorExit:
                raise
            except Exception as raw_error:
                if (
                    attempt is not None
                    and not attempt.accepted
                    and not stream_opened
                    and not prompt_cache_breakpoint_fallback_used
                    and _is_prompt_cache_breakpoint_rejection(raw_error)
                ):
                    # Some private Codex-compatible endpoints advertise a
                    # GPT-5.6 model but still reject the public explicit
                    # breakpoint field. Correct the request shape once, then
                    # remember the process-local capability downgrade so all
                    # subsequent requests avoid a predictable 400.
                    prompt_cache_breakpoint_fallback_used = True
                    self._supports_explicit_prompt_cache_breakpoints = False
                    body = _body_without_prompt_cache_breakpoint(body)
                    await attempt.retry_immediately()
                    recovery.discard()
                    trace_event(
                        stage="provider",
                        event="provider.prompt_cache_breakpoint.fallback",
                        source="provider",
                        provider="openai",
                        request_id=request_id,
                        gateway_model=response_model,
                    )
                    continue
                error = _effective_error(raw_error)
                if (
                    attempt is not None
                    and not attempt.accepted
                    and not recovery.committed
                ):
                    await attempt.retry(error)
                retryable = (
                    attempt.failure_retryable
                    if attempt is not None and attempt.failure_retryable is not None
                    else None
                )
                decision = recovery.advance_failure(
                    error,
                    stream_opened=stream_opened,
                    generated_output=recovery.committed,
                    complete_tool_salvageable=False,
                    attempts_remaining=retry_session.attempts_remaining,
                    retryable_override=retryable,
                )
                if (
                    not decision.committed
                    and decision.retryable
                    and retry_session.can_attempt
                ):
                    recovery.discard()
                    trace_event(
                        stage="provider",
                        event="provider.recovery.early_retry",
                        source="provider",
                        provider="openai",
                        request_id=request_id,
                        attempts_started=retry_session.attempts_started,
                        max_attempts=retry_session.max_attempts,
                    )
                    continue

                failure = classify_provider_failure(
                    error,
                    provider_name="OpenAI",
                    read_timeout_s=self._config.http_read_timeout,
                    request_id=request_id,
                )
                (
                    fault_domain,
                    fault_confidence,
                    fault_evidence_codes,
                ) = self._classify_stream_failure("OPENAI", error)
                self._log_stream_transport_error(
                    "OPENAI",
                    f" request_id={request_id}" if request_id else "",
                    error,
                    request_id=request_id,
                )
                trace_event(
                    stage="provider",
                    event="provider.response.error",
                    source="provider",
                    provider="openai",
                    request_id=request_id,
                    exc_type=type(error).__name__,
                    failure_kind=failure.kind.value,
                    status_code=failure.status_code,
                    provider_retryable=failure.retryable,
                    fault_domain=fault_domain.value,
                    confidence=fault_confidence.value,
                    evidence_codes=fault_evidence_codes,
                )
                if not decision.committed:
                    recovery.discard()
                    raise failure from raw_error
                for event in stream.ledger.close_unclosed_blocks():
                    yield event
                raise failure from raw_error
            finally:
                if response is not None:
                    await response.aclose()
                if attempt is not None:
                    await attempt.aclose()

        raise RuntimeError("OpenAI retry session ended without a terminal result.")


async def _iter_sse(
    response: httpx.Response,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    event_type = ""
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if not data_lines:
                event_type = ""
                continue
            raw_data = "\n".join(data_lines)
            data_lines = []
            if raw_data == "[DONE]":
                return
            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError as exc:
                raise _TruncatedResponsesStream(
                    "OpenAI returned malformed Responses SSE."
                ) from exc
            if not isinstance(payload, dict):
                raise _TruncatedResponsesStream(
                    "OpenAI returned a non-object Responses event."
                )
            resolved_type = event_type or payload.get("type")
            event_type = ""
            if isinstance(resolved_type, str) and resolved_type:
                yield resolved_type, payload
            continue
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        raise _TruncatedResponsesStream(
            "OpenAI Responses stream ended during an SSE event."
        )


async def _read_bounded_body(
    response: httpx.Response,
) -> tuple[bytes, bool]:
    limit = ERROR_DETAIL_DISPLAY_CAP_BYTES
    body = bytearray()
    async for chunk in response.aiter_bytes():
        remaining = limit + 1 - len(body)
        if remaining <= 0:
            break
        body.extend(chunk[:remaining])
        if len(body) > limit:
            break
    truncated = len(body) > limit
    return bytes(body[:limit]), truncated


def _safe_metadata_identifier(value: str | None, *, fallback: str) -> str:
    """Keep caller-provided IDs out of HTTP metadata when they are unsafe."""

    if not isinstance(value, str) or not value.strip():
        return fallback
    candidate = value.strip()
    if len(candidate) > _MAX_CODEX_METADATA_IDENTIFIER_LENGTH or any(
        ord(character) < 0x21 or ord(character) > 0x7E for character in candidate
    ):
        return fallback
    return candidate


def _responses_lite_transport_headers(
    body: dict[str, Any], *, installation_id: str
) -> dict[str, str]:
    """Return the bounded transport projections used by native Codex."""

    headers: dict[str, str] = {CODEX_RESPONSES_LITE_HEADER: "true"}
    if installation_id:
        headers[CODEX_INSTALLATION_ID_HEADER] = installation_id
    client_metadata = body.get("client_metadata")
    if isinstance(client_metadata, dict):
        # Native compatibility headers are window, bounded turn-metadata,
        # parent-thread, and subagent. Thread/session identity travels in the
        # caller's session headers.
        headers.update(codex_compatibility_headers(client_metadata))
    return headers


def _wire_tool_count(body: dict[str, Any]) -> int:
    """Count ordinary and Lite-namespaced tools for bounded trace metadata."""

    tools = body.get("tools")
    if isinstance(tools, list):
        return len(tools)
    input_items = body.get("input")
    if not isinstance(input_items, list):
        return 0
    count = 0
    for item in input_items:
        if not isinstance(item, dict) or item.get("type") != "additional_tools":
            continue
        additional = item.get("tools")
        if not isinstance(additional, list):
            continue
        for tool in additional:
            if isinstance(tool, dict) and tool.get("type") == "namespace":
                nested = tool.get("tools")
                count += len(nested) if isinstance(nested, list) else 0
            else:
                count += 1
    return count


def _auth_headers(access: OpenAIAccess) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access.access_token}",
        "ChatGPT-Account-ID": access.account_id,
    }
    if access.fedramp:
        headers["X-OpenAI-Fedramp"] = "true"
    return headers


def _is_prompt_cache_breakpoint_rejection(error: Exception) -> bool:
    """Return whether an HTTP 400 specifically rejects the cache breakpoint."""

    if (
        not isinstance(error, httpx.HTTPStatusError)
        or error.response.status_code != 400
    ):
        return False
    body_text = extract_upstream_error_detail(error).body_text
    if not body_text:
        return False
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    provider_error = payload.get("error")
    if not isinstance(provider_error, dict):
        return False
    if provider_error.get("param") != "prompt_cache_breakpoint":
        return False
    code = provider_error.get("code")
    if isinstance(code, str) and code.casefold() in {
        "invalid_parameter",
        "unsupported_parameter",
    }:
        return True
    message = provider_error.get("message")
    if not isinstance(message, str):
        return False
    normalized = message.casefold()
    return "prompt_cache_breakpoint" in normalized and "not supported" in normalized


def _body_without_prompt_cache_breakpoint(body: dict[str, Any]) -> dict[str, Any]:
    """Restore the pre-breakpoint request shape without mutating ``body``."""

    cleaned = _copy_without_prompt_cache_breakpoint(body)
    if not isinstance(cleaned, dict):
        return dict(body)

    input_items = cleaned.get("input")
    if not isinstance(input_items, list) or not input_items:
        return cleaned
    first_item = input_items[0]
    if not isinstance(first_item, dict) or first_item.get("role") != "developer":
        return cleaned

    content = first_item.get("content")
    instruction_parts: list[str] = []
    if isinstance(content, str):
        instruction_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "input_text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                instruction_parts.append(text)
    if not instruction_parts:
        return cleaned

    cleaned["instructions"] = "\n\n".join(instruction_parts)
    cleaned["input"] = input_items[1:]
    return cleaned


def _copy_without_prompt_cache_breakpoint(value: Any) -> Any:
    """Recursively copy JSON-like request data while removing one field."""

    if isinstance(value, dict):
        return {
            key: _copy_without_prompt_cache_breakpoint(item)
            for key, item in value.items()
            if key != "prompt_cache_breakpoint"
        }
    if isinstance(value, list):
        return [_copy_without_prompt_cache_breakpoint(item) for item in value]
    return value


def _model_infos(payload: Any) -> frozenset[ProviderModelInfo]:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise ValueError("OpenAI model-list response is missing the models array.")
    infos: set[ProviderModelInfo] = set()
    for model in payload["models"]:
        if not isinstance(model, dict):
            continue
        model_id = model.get("slug")
        visibility = model.get("visibility")
        if (
            not isinstance(model_id, str)
            or not model_id.strip()
            or visibility != "list"
        ):
            continue
        efforts = model.get(
            "supported_reasoning_levels",
            model.get("supported_reasoning_efforts"),
        )
        infos.add(
            ProviderModelInfo(
                model_id=model_id,
                supports_thinking=bool(efforts) if isinstance(efforts, list) else None,
            )
        )
    if not infos:
        raise ValueError("OpenAI did not advertise any visible models.")
    return frozenset(infos)


def _effective_error(error: Exception) -> Exception:
    if isinstance(error, OpenAIReconnectRequired):
        return ExecutionFailure(
            kind=FailureKind.AUTHENTICATION,
            status_code=401,
            message=str(error),
            retryable=False,
        )
    if isinstance(error, ResponsesStreamFailure):
        message = (
            extract_upstream_error_detail(error).exception_text
            or "OpenAI response failed."
        )
        code = (error.code or "").lower()
        if "rate" in code or "429" in code:
            return ExecutionFailure(FailureKind.RATE_LIMIT, 429, message, True)
        if any(marker in code for marker in ("overload", "capacity", "529")):
            return ExecutionFailure(FailureKind.OVERLOADED, 529, message, True)
        retryable = any(
            marker in code
            for marker in ("server", "internal", "unavailable", "timeout")
        )
        return ExecutionFailure(FailureKind.UPSTREAM, 502, message, retryable)
    return error
