from collections.abc import AsyncIterator
from unittest.mock import patch

import httpx

from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from free_claude_code.providers.base import BaseProvider, ProviderConfig


class _TraceProbeProvider(BaseProvider):
    def preflight_stream(
        self,
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> None:
        raise NotImplementedError

    async def cleanup(self) -> None:
        return None

    async def list_model_infos(self) -> frozenset[ProviderModelInfo]:
        return frozenset()

    def stream_response(
        self,
        request: MessagesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> AsyncIterator[str]:
        raise NotImplementedError


def _provider() -> _TraceProbeProvider:
    return _TraceProbeProvider(
        ProviderConfig(api_key="test-key", base_url="https://example.invalid")
    )


def test_ambiguous_transport_trace_does_not_blame_harness() -> None:
    with patch("free_claude_code.providers.base.trace_event") as trace:
        _provider()._log_stream_transport_error(
            "TEST", " request_id=req", ConnectionError("socket reset"), request_id="req"
        )

    receipt = trace.call_args.kwargs
    assert receipt["fault_domain"] == "unknown"
    assert receipt["confidence"] == "medium"
    assert receipt["evidence_codes"] == ["transport_failure_ownership_unproven"]


def test_http_status_trace_attributes_explicit_upstream_response() -> None:
    request = httpx.Request("POST", "https://example.invalid/v1/messages")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError(
        "service unavailable",
        request=request,
        response=response,
    )

    with patch("free_claude_code.providers.base.trace_event") as trace:
        _provider()._log_stream_transport_error(
            "TEST", " request_id=req", error, request_id="req"
        )

    receipt = trace.call_args.kwargs
    assert receipt["http_status"] == 503
    assert receipt["fault_domain"] == "opencode_gateway"
    assert receipt["confidence"] == "high"
    assert receipt["evidence_codes"] == ["upstream_error:http_503"]
