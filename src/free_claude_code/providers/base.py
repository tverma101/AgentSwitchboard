"""Base provider interface - extend this to implement your own provider."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

from loguru import logger

from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.config.constants import HTTP_CONNECT_TIMEOUT_DEFAULT
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.diagnostics import (
    exception_cause_types,
    redacted_exception_traceback,
)
from free_claude_code.core.provider_policy import (
    ProviderEgressGuard,
    ProviderPolicyError,
)
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from free_claude_code.core.trace import trace_event


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Resolved immutable configuration for one provider instance.

    Base fields apply to all providers. Provider-specific parameters
    (e.g. NIM temperature, top_p) are passed by the provider constructor.
    """

    api_key: str
    base_url: str
    rate_limit: int | None = None
    rate_window: int = 60
    max_concurrency: int = 5
    http_read_timeout: float = 300.0
    http_write_timeout: float = 10.0
    http_connect_timeout: float = HTTP_CONNECT_TIMEOUT_DEFAULT
    proxy: str = ""
    log_raw_sse_events: bool = False
    log_api_error_tracebacks: bool = False
    provider_family: str = ""
    egress_guard: ProviderEgressGuard | None = None


class BaseProvider(ABC):
    """Base class for all providers. Extend this to add your own."""

    def __init__(self, config: ProviderConfig):
        self._config = config

    def bind_egress_guard(self, guard: ProviderEgressGuard) -> None:
        """Bind one runtime guard without changing the immutable policy."""
        self._config = replace(self._config, egress_guard=guard)

    @abstractmethod
    def preflight_stream(
        self,
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> None:
        """Validate the upstream request before opening an SSE stream."""

    def _log_stream_transport_error(
        self,
        tag: str,
        req_tag: str,
        error: Exception,
        *,
        request_id: str | None = None,
    ) -> None:
        """Log streaming transport failures (metadata-only unless verbose is enabled)."""
        response = getattr(error, "response", None)
        http_status = (
            getattr(response, "status_code", None) if response is not None else None
        )
        cause_types = exception_cause_types(error)
        trace_event(
            stage="provider",
            event="provider.response.transport_error",
            source="provider",
            provider=tag,
            request_id=request_id,
            exc_type=type(error).__name__,
            http_status=http_status,
            cause_types=cause_types,
            fault_domain="harness_transport",
            confidence="medium",
            evidence_codes=["provider_transport_error"],
        )

        if self._config.log_api_error_tracebacks:
            logger.error(
                "{}_ERROR:{} exc_type={}\n{}",
                tag,
                req_tag,
                type(error).__name__,
                redacted_exception_traceback(error),
            )
            return
        logger.error(
            "{}_ERROR:{} exc_type={} http_status={} cause_types={}",
            tag,
            req_tag,
            type(error).__name__,
            http_status,
            ",".join(cause_types) if cause_types else None,
        )

    def _authorize_egress(
        self,
        url: str,
        *,
        category: str = "model",
        model: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Enforce an optional launch-time egress policy before network I/O."""
        guard = self._config.egress_guard
        if guard is None:
            return
        allowed = guard.authorize_url(
            url,
            category=category,
            model=model,
            provider_family=self._config.provider_family or None,
            session_id=session_id,
            request_id=request_id,
        )
        if not allowed:
            raise ProviderPolicyError(
                "provider egress blocked before network I/O by diagnostic policy"
            )

    @abstractmethod
    async def cleanup(self) -> None:
        """Release any resources held by this provider."""

    @abstractmethod
    async def list_model_infos(self) -> frozenset[ProviderModelInfo]:
        """Return the model metadata currently advertised by this provider."""

    @abstractmethod
    def stream_response(
        self,
        request: MessagesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> AsyncIterator[str]:
        """Stream response in Anthropic SSE format."""
