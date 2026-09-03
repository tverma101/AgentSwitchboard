"""OpenAI routing + Codex wire-parity regressions.

Covers the live contract for ``openai/...`` models inside Claude Code:
direct routing, subagent inheritance, token-probe isolation, generation
scoping, compaction continuity, and the native Codex transport projections
(session/thread headers, stable installation, thread-scoped Lite IDs,
bounded compatibility headers, and within-turn sticky routing).
"""

import json

import httpx
import pytest

from free_claude_code.application.routing import ModelRouter, ParentRouteRegistry
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.models import Message, MessagesRequest
from free_claude_code.core.openai_responses import (
    CODEX_INSTALLATION_ID_HEADER,
    CODEX_RESPONSES_LITE_HEADER,
    codex_client_metadata,
    codex_compatibility_headers,
    codex_model_profile,
    codex_session_headers,
    lite_item_id,
    load_or_create_installation_id,
)
from free_claude_code.core.openai_responses.provider_input import (
    build_responses_lite_provider_request,
)
from free_claude_code.core.reasoning import (
    DEFAULT_REASONING_POLICY,
    ReasoningEffort,
    ReasoningPolicy,
)
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.openai_codex.auth import (
    OpenAIAccess,
    OpenAIAuthManager,
)
from free_claude_code.providers.openai_codex.provider import OpenAICodexProvider


def _openai_settings(
    model: str = "openai/gpt-5.6-luna",
    model_haiku: str = "openai/gpt-5.6-luna",
    subagent_model_inherit: bool = True,
    reasoning_policy: ReasoningPreference = ReasoningPreference.CLIENT,
    reasoning_opus: ReasoningPreference = ReasoningPreference.INHERIT,
) -> Settings:
    return Settings().model_copy(
        update={
            "model": model,
            "model_haiku": model_haiku,
            "subagent_model_inherit": subagent_model_inherit,
            "reasoning_policy": reasoning_policy,
            "reasoning_opus": reasoning_opus,
        }
    )


def _request(model: str, session: str | None = "sess-1") -> MessagesRequest:
    payload: dict[str, object] = {
        "model": model,
        "messages": [Message(role="user", content="hello")],
    }
    request = MessagesRequest.model_validate(payload)
    if session is not None:
        request = request.model_copy(update={"claude_session_id": session})
    return request


def test_direct_openai_model_routes_to_openai_provider() -> None:
    router = ModelRouter(_openai_settings())
    resolved = router.resolve("openai/gpt-5.6-luna")

    assert resolved.provider_id == "openai"
    assert resolved.provider_model == "gpt-5.6-luna"
    assert resolved.provider_model_ref == "openai/gpt-5.6-luna"
    assert resolved.route_source == "request_model"


def test_direct_openai_non_lite_model_still_routes_to_openai() -> None:
    router = ModelRouter(_openai_settings())
    resolved = router.resolve("openai/gpt-5.4")

    assert resolved.provider_id == "openai"
    assert resolved.provider_model == "gpt-5.4"
    # Only audited IDs get the Lite dialect; routing must not depend on it.
    assert codex_model_profile("gpt-5.4") is None
    assert codex_model_profile("gpt-5.6-luna") is not None


def test_openai_subagent_inherits_parent_route() -> None:
    router = ModelRouter(_openai_settings())
    parent = router.resolve("openai/gpt-5.6-luna")
    child = router.resolve("claude-3-haiku-20240307", parent_route=parent)

    assert child.provider_id == "openai"
    assert child.provider_model == "gpt-5.6-luna"
    assert child.route_source == "parent_inherited"
    assert child.reasoning_preference is parent.reasoning_preference


def test_openai_subagent_can_opt_out_of_inheritance() -> None:
    router = ModelRouter(_openai_settings(subagent_model_inherit=False))
    parent = router.resolve("openai/gpt-5.6-luna")
    child = router.resolve("claude-3-haiku-20240307", parent_route=parent)

    assert child.provider_model_ref == "openai/gpt-5.6-luna"
    assert child.route_source == "model_haiku"


def test_openai_parent_route_survives_compaction_turn() -> None:
    """Same Claude session after compact must keep the parent provider/model."""

    registry = ParentRouteRegistry()
    router = ModelRouter(_openai_settings())
    parent = router.resolve("openai/gpt-5.6-luna")
    registry.remember("compact-session", parent, generation_id=3)

    # A post-compact child tier (e.g. Haiku-named subagent) still inherits.
    remembered = registry.lookup("compact-session", generation_id=3)
    assert remembered is not None
    child = router.resolve("claude-3-haiku-20240307", parent_route=remembered)

    assert child.provider_model_ref == "openai/gpt-5.6-luna"
    assert child.route_source == "parent_inherited"


def test_openai_token_probe_does_not_poison_parent_route() -> None:
    registry = ParentRouteRegistry()
    router = ModelRouter(_openai_settings())
    probe = router.resolve("openai/gpt-5.6-luna")
    registry.remember_probe("probe-session", probe, generation_id=9)

    assert registry.lookup("probe-session", generation_id=9) is None
    assert registry.lookup_probe("probe-session", generation_id=9) is probe

    # Authoritative parent replaces the probe hint.
    parent = router.resolve("openai/gpt-5.6-sol")
    registry.remember("probe-session", parent, generation_id=9)
    assert registry.lookup("probe-session", generation_id=9) is parent


def test_openai_parent_route_is_generation_scoped() -> None:
    registry = ParentRouteRegistry()
    router = ModelRouter(_openai_settings())
    parent = router.resolve("openai/gpt-5.6-terra")
    registry.remember("gen-session", parent, generation_id=7)

    assert registry.lookup("gen-session", generation_id=7) is parent
    assert registry.lookup("gen-session", generation_id=8) is None


def test_openai_reasoning_preference_uses_root_policy_for_direct_ref() -> None:
    settings = _openai_settings(
        reasoning_policy=ReasoningPreference.LOW,
        reasoning_opus=ReasoningPreference.MAX,
    )
    routed = ModelRouter(settings).resolve_messages_request(
        _request("openai/gpt-5.6-luna")
    )

    assert routed.resolved.provider_id == "openai"
    assert routed.reasoning == ReasoningPolicy.on(effort=ReasoningEffort.LOW)


def test_lite_item_ids_are_thread_scoped_and_stable() -> None:
    tools = [{"type": "function", "name": "Read"}]

    first_a = lite_item_id("at", tools, "thread-a")
    second_a = lite_item_id("at", tools, "thread-a")
    first_b = lite_item_id("at", tools, "thread-b")

    assert first_a == second_a
    assert first_a.startswith("at_")
    assert first_a != first_b


def test_lite_prefix_ids_stable_across_compaction_history() -> None:
    """Same thread+tools keeps prefix IDs when history grows (compact)."""

    profile = codex_model_profile("gpt-5.6-luna")
    assert profile is not None
    base = {
        "model": "gpt-5.6-luna",
        "system": "Stable harness context",
        "tools": [
            {
                "name": "Read",
                "description": "Read",
                "input_schema": {"type": "object"},
            }
        ],
    }
    first = MessagesRequest.model_validate(
        {**base, "messages": [{"role": "user", "content": "hello"}]}
    )
    second = MessagesRequest.model_validate(
        {
            **base,
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "summary after compact"},
                {"role": "user", "content": "continue"},
            ],
        }
    )

    first_body = build_responses_lite_provider_request(
        first,
        reasoning=DEFAULT_REASONING_POLICY,
        profile=profile,
        thread_id="thread-compact",
    )
    second_body = build_responses_lite_provider_request(
        second,
        reasoning=DEFAULT_REASONING_POLICY,
        profile=profile,
        thread_id="thread-compact",
    )

    assert first_body["input"][0]["id"] == second_body["input"][0]["id"]
    assert first_body["input"][1]["id"] == second_body["input"][1]["id"]


def test_client_metadata_root_turn_omits_parent_and_subagent() -> None:
    metadata = codex_client_metadata(
        installation_id="install-1",
        session_id="sess-1",
        thread_id="thread-1",
        turn_id="turn-1",
        window_id="thread-1:0",
    )

    assert metadata["session_id"] == "sess-1"
    assert metadata["thread_id"] == "thread-1"
    assert "x-codex-parent-thread-id" not in metadata
    assert "x-openai-subagent" not in metadata
    turn = json.loads(metadata["x-codex-turn-metadata"])
    assert turn["request_kind"] == "turn"
    assert "parent_thread_id" not in turn
    assert "subagent" not in turn


def test_compatibility_headers_are_bounded_projections() -> None:
    metadata = codex_client_metadata(
        installation_id="install-1",
        session_id="sess-1",
        thread_id="thread-1",
        turn_id="turn-1",
        window_id="thread-1:0",
    )
    headers = codex_compatibility_headers(metadata)

    assert headers["x-codex-window-id"] == "thread-1:0"
    assert headers["x-codex-turn-metadata"] == metadata["x-codex-turn-metadata"]
    assert CODEX_INSTALLATION_ID_HEADER not in headers


def test_session_headers_match_native_contract() -> None:
    headers = codex_session_headers(session_id="sess-1", thread_id="thread-1")

    assert headers == {"session-id": "sess-1", "thread-id": "thread-1"}


def test_installation_id_is_stable_per_config_dir(tmp_path) -> None:
    first = load_or_create_installation_id(tmp_path)
    second = load_or_create_installation_id(tmp_path)

    assert first == second
    assert len(first) > 0


class _FakeAuth(OpenAIAuthManager):
    async def access(self, *, force_refresh: bool = False) -> OpenAIAccess:
        return OpenAIAccess("token-1", "account-1", False)


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        api_key="",
        base_url="https://chatgpt.com/backend-api/codex",
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
    import json as _json

    def _event(event_type: str, payload: dict[str, object]) -> str:
        return f"event: {event_type}\ndata: {_json.dumps(payload)}\n\n"

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


@pytest.mark.asyncio
async def test_lite_transport_sends_native_session_and_installation_headers() -> None:
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
        _provider_config(),
        auth=_FakeAuth(),
        admission=_admission(),
        client=client,
        responses_lite_enabled=True,
        installation_id="install-fixed",
    )
    request = MessagesRequest.model_validate(
        {
            "model": "gpt-5.6-luna",
            "messages": [{"role": "user", "content": "hello"}],
            "claude_session_id": "thread-abc",
        }
    )

    body_text = "".join(
        [
            chunk
            async for chunk in provider.stream_response(
                request, request_id="turn-1", response_model="openai/gpt-5.6-luna"
            )
        ]
    )

    assert "hello" in body_text
    upstream = seen[0]
    assert upstream.headers[CODEX_RESPONSES_LITE_HEADER] == "true"
    assert upstream.headers[CODEX_INSTALLATION_ID_HEADER] == "install-fixed"
    assert upstream.headers["session-id"]
    assert upstream.headers["thread-id"] == "thread-abc"
    payload = json.loads(upstream.content)
    assert payload["client_metadata"]["thread_id"] == "thread-abc"
    assert payload["client_metadata"]["x-codex-installation-id"] == "install-fixed"
    await client.aclose()


@pytest.mark.asyncio
async def test_turn_state_is_replayed_within_one_turn_only() -> None:
    seen: list[httpx.Request] = []
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        seen.append(request)
        if attempts == 1:
            return httpx.Response(
                500,
                json={"error": {"message": "transient"}},
                headers={"x-codex-turn-state": "sticky-123"},
                request=request,
            )
        return httpx.Response(
            200,
            text=_complete_stream("recovered"),
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    client = httpx.AsyncClient(
        base_url="https://chatgpt.com/backend-api/codex/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICodexProvider(
        _provider_config(),
        auth=_FakeAuth(),
        admission=_admission(),
        client=client,
        installation_id="install-fixed",
    )
    request = MessagesRequest.model_validate(
        {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]}
    )

    body_text = "".join(
        [chunk async for chunk in provider.stream_response(request, request_id="r1")]
    )

    assert attempts == 2
    assert "x-codex-turn-state" not in seen[0].headers
    assert seen[1].headers["x-codex-turn-state"] == "sticky-123"
    assert "recovered" in body_text
    await client.aclose()
