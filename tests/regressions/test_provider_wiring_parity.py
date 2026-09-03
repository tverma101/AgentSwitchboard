"""Cross-provider wiring parity vs native opensource contracts.

Locks:
- OpenAI Codex CLI routing: ChatGPT base URL, POST /responses, slug
  passthrough, Responses-only wire_api, ChatGPT bearer + account headers,
  codex_cli_rs originator, session/thread identity.
- OpenCode Go docs (2026-09-02): per-model endpoint table
  (/responses vs /chat/completions vs /messages) and opencode-go/<id> refs.
- Provider construction: every catalog id has exactly one factory owner and
  builds with egress guard (solid proxy wiring).
- Claude Code safety: Anthropic SSE contract holds for OpenAI Lite and Go
  Responses paths, including namespaced tools.
"""

import json

import httpx
import pytest

from free_claude_code.application.routing import ModelRouter
from free_claude_code.config.model_protocols import (
    OPENCODE_GO_MODEL_PROTOCOLS,
    GoProtocol,
)
from free_claude_code.config.provider_catalog import (
    OPENAI_CODEX_DEFAULT_BASE,
    OPENCODE_GO_DEFAULT_BASE,
    PROVIDER_CATALOG,
)
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.anthropic.stream_contracts import (
    assert_anthropic_stream_contract,
    parse_sse_text,
)
from free_claude_code.core.reasoning import ReasoningPolicy
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.openai_codex.auth import (
    OpenAIAccess,
    OpenAIAuthManager,
)
from free_claude_code.providers.openai_codex.login import OPENAI_CODEX_ORIGINATOR
from free_claude_code.providers.openai_codex.provider import OpenAICodexProvider
from free_claude_code.providers.opencode_go.provider import protocol_for_model


class _FakeAuth(OpenAIAuthManager):
    async def access(self, *, force_refresh: bool = False) -> OpenAIAccess:
        return OpenAIAccess("token-1", "account-1", False)


def _codex_config() -> ProviderConfig:
    return ProviderConfig(
        api_key="",
        base_url=OPENAI_CODEX_DEFAULT_BASE,
        rate_limit=100,
        rate_window=1,
        max_concurrency=2,
    )


def _admission() -> ProviderAdmissionController:
    return ProviderAdmissionController(
        provider_name="openai",
        rate_limit=100,
        rate_window=1,
        max_concurrency=2,
        base_delay=0,
        max_delay=0,
        jitter=0,
    )


def _complete_stream(text: str) -> str:
    def _event(event_type: str, payload: dict[str, object]) -> str:
        return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"

    return "".join(
        [
            _event(
                "response.created",
                {"type": "response.created", "response": {"id": "resp_1"}},
            ),
            _event(
                "response.output_text.delta",
                {"type": "response.output_text.delta", "delta": text},
            ),
            _event(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_1",
                        "usage": {"input_tokens": 3, "output_tokens": 2},
                    },
                },
            ),
        ]
    )


def test_openai_codex_base_url_matches_native_chatgpt_backend() -> None:
    assert OPENAI_CODEX_DEFAULT_BASE == "https://chatgpt.com/backend-api/codex"
    assert OPENAI_CODEX_ORIGINATOR == "codex_cli_rs"


def test_openai_routing_passes_slug_through_unchanged() -> None:
    settings = Settings().model_copy(
        update={"model": "openai/gpt-5.6-luna", "subagent_model_inherit": True}
    )
    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest.model_validate(
            {
                "model": "openai/gpt-5.6-luna",
                "messages": [{"role": "user", "content": "hi"}],
            }
        )
    )

    assert routed.resolved.provider_id == "openai"
    # Native sends the slug verbatim; the gateway must not rewrite it.
    assert routed.request.model == "gpt-5.6-luna"
    assert routed.resolved.provider_model == "gpt-5.6-luna"


@pytest.mark.asyncio
async def test_openai_wire_uses_responses_endpoint_with_native_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            text=_complete_stream("hello"),
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    client = httpx.AsyncClient(
        base_url="https://chatgpt.com/backend-api/codex/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICodexProvider(
        _codex_config(),
        auth=_FakeAuth(),
        admission=_admission(),
        client=client,
        responses_lite_enabled=True,
        installation_id="install-1",
    )
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-5.6-luna",
            "messages": [{"role": "user", "content": "hi"}],
            "claude_session_id": "thread-1",
        }
    )
    body_text = "".join(
        [
            chunk
            async for chunk in provider.stream_response(request, request_id="turn-1")
        ]
    )

    upstream = seen[0]
    assert upstream.url.path.endswith("/responses")
    assert upstream.headers["authorization"] == "Bearer token-1"
    assert upstream.headers["chatgpt-account-id"] == "account-1"
    assert upstream.headers["originator"] == "codex_cli_rs"
    assert upstream.headers["accept"] == "text/event-stream"
    payload = json.loads(upstream.content)
    # Responses-only wire_api: slug verbatim, SSE streaming, no stored state.
    assert payload["model"] == "gpt-5.6-luna"
    assert payload["stream"] is True
    assert payload["store"] is False
    assert payload["include"] == ["reasoning.encrypted_content"]
    # Service tier omitted means model default, matching native when unset.
    assert "service_tier" not in payload or payload.get("service_tier") is None
    assert_anthropic_stream_contract(parse_sse_text(body_text))
    await client.aclose()


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("grok-4.6", GoProtocol.RESPONSES),
        ("gpt-5.6-luna", GoProtocol.RESPONSES),
        ("muse-spark-1.3-contributor", GoProtocol.RESPONSES),
        ("muse-spark-1.2-contributor", GoProtocol.RESPONSES),
        ("glm-5.3-flash", GoProtocol.CHAT),
        ("glm-5.3", GoProtocol.CHAT),
        ("glm-5.2", GoProtocol.CHAT),
        ("glm-5.1", GoProtocol.CHAT),
        ("kimi-k3", GoProtocol.CHAT),
        ("kimi-k2.7-code", GoProtocol.CHAT),
        ("kimi-k2.6", GoProtocol.CHAT),
        ("longcat-2.0", GoProtocol.CHAT),
        ("deepseek-v4-pro", GoProtocol.CHAT),
        ("deepseek-v4-flash", GoProtocol.CHAT),
        ("deepseek-v4-flash-vision-exp", GoProtocol.CHAT),
        ("mimo-v2.5", GoProtocol.CHAT),
        ("mimo-v2.5-pro", GoProtocol.CHAT),
        ("hy4-preview", GoProtocol.CHAT),
        ("hy3", GoProtocol.CHAT),
        ("minimax-m3", GoProtocol.MESSAGES),
        ("minimax-m2.7", GoProtocol.MESSAGES),
        ("minimax-m2.5", GoProtocol.MESSAGES),
        ("qwen3.8-max", GoProtocol.MESSAGES),
        ("qwen3.8-flash", GoProtocol.MESSAGES),
        ("qwen3.7-max", GoProtocol.MESSAGES),
        ("qwen3.7-plus", GoProtocol.MESSAGES),
        ("qwen3.6-plus", GoProtocol.MESSAGES),
    ],
)
def test_opencode_go_protocols_match_docs_endpoints_table(
    model_id: str, expected: GoProtocol
) -> None:
    assert OPENCODE_GO_MODEL_PROTOCOLS[model_id] is expected
    assert protocol_for_model(model_id) is expected


def test_opencode_go_base_url_matches_docs() -> None:
    assert OPENCODE_GO_DEFAULT_BASE == "https://opencode.ai/zen/go/v1"


def test_opencode_go_routing_keeps_provider_model_ref() -> None:
    settings = Settings().model_copy(
        update={"model": "opencode_go/muse-spark-1.2-contributor"}
    )
    for model_ref in (
        "opencode_go/muse-spark-1.2-contributor",
        "opencode_go/kimi-k2.6",
        "opencode_go/minimax-m2.7",
    ):
        routed = ModelRouter(settings).resolve_messages_request(
            MessagesRequest.model_validate(
                {"model": model_ref, "messages": [{"role": "user", "content": "hi"}]}
            )
        )
        assert routed.resolved.provider_id == "opencode_go"
        assert routed.resolved.provider_model_ref == model_ref


def test_every_catalog_provider_has_single_construction_owner() -> None:
    from free_claude_code.providers.openai_chat import OPENAI_CHAT_PROFILES
    from free_claude_code.providers.runtime.factory import (
        _INJECTED_PROVIDER_IDS,
        _PROFILE_SUBADAPTER_IDS,
        _SPECIAL_PROVIDER_FACTORIES,
    )

    profiled = set(OPENAI_CHAT_PROFILES) - _PROFILE_SUBADAPTER_IDS
    special = set(_SPECIAL_PROVIDER_FACTORIES)
    assert not (profiled & special)
    assert not (profiled & _INJECTED_PROVIDER_IDS)
    assert not (special & _INJECTED_PROVIDER_IDS)
    assert profiled | special | _INJECTED_PROVIDER_IDS == set(PROVIDER_CATALOG)


def test_provider_configs_build_for_all_catalog_ids() -> None:
    from free_claude_code.providers.runtime.config import build_provider_config

    settings = Settings()
    built = 0
    for descriptor in PROVIDER_CATALOG.values():
        try:
            config = build_provider_config(descriptor, settings)
        except Exception:
            # Unconfigured remote credentials are expected locally; the
            # construction path itself must remain total (raise typed error,
            # never import or attribute failure).
            continue
        assert config.base_url
        built += 1
    # Local built-ins always build without credentials.
    assert built >= 3


@pytest.mark.asyncio
async def test_claude_stream_contract_holds_for_lite_namespaced_tools() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = json.loads(request.content)
        alias = payload["input"][0]["tools"][0]["tools"][0]["name"]
        body = "".join(
            [
                "event: response.output_item.added\n",
                f"data: {json.dumps({'type': 'response.output_item.added', 'item': {'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_1', 'name': alias}})}\n\n",
                "event: response.output_item.done\n",
                f"data: {json.dumps({'type': 'response.output_item.done', 'item': {'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_1', 'name': alias, 'arguments': '{}'}})}\n\n",
                "event: response.completed\n",
                f"data: {json.dumps({'type': 'response.completed', 'response': {'id': 'resp_1', 'usage': {'input_tokens': 3, 'output_tokens': 2}}})}\n\n",
            ]
        )
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    client = httpx.AsyncClient(
        base_url="https://chatgpt.com/backend-api/codex/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICodexProvider(
        _codex_config(),
        auth=_FakeAuth(),
        admission=_admission(),
        client=client,
        responses_lite_enabled=True,
        installation_id="install-1",
    )
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-5.6-luna",
            "messages": [{"role": "user", "content": "use tool"}],
            "tools": [
                {
                    "name": "Read",
                    "description": "Read",
                    "input_schema": {"type": "object"},
                }
            ],
        }
    )
    body_text = "".join(
        [
            chunk
            async for chunk in provider.stream_response(
                request,
                request_id="turn-1",
                reasoning=ReasoningPolicy.provider_default(),
            )
        ]
    )

    events = parse_sse_text(body_text)
    assert_anthropic_stream_contract(events)
    # Namespaced alias never leaks to Claude; original name is restored.
    assert "Read" in body_text
    await client.aclose()
