from unittest.mock import patch

import pytest

from free_claude_code.application.errors import UnknownProviderError
from free_claude_code.application.routing import (
    ModelRouter,
    ParentRouteRegistry,
    ResolvedModel,
)
from free_claude_code.config.provider_catalog import PROVIDER_CATALOG
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.models import (
    Message,
    MessagesRequest,
    TokenCountRequest,
)
from free_claude_code.core.reasoning import ReasoningControl, ReasoningEffort


@pytest.fixture
def settings():
    settings = Settings()
    settings.model = "nvidia_nim/fallback-model"
    settings.model_fable = None
    settings.model_opus = None
    settings.model_sonnet = None
    settings.model_haiku = None
    settings.subagent_model_inherit = False
    settings.reasoning_policy = ReasoningPreference.CLIENT
    settings.reasoning_fable = ReasoningPreference.INHERIT
    settings.reasoning_opus = ReasoningPreference.INHERIT
    settings.reasoning_sonnet = ReasoningPreference.INHERIT
    settings.reasoning_haiku = ReasoningPreference.INHERIT
    return settings


def test_model_router_resolves_default_model(settings):
    resolved = ModelRouter(settings).resolve("claude-3-opus")

    assert resolved.original_model == "claude-3-opus"
    assert resolved.provider_id == "nvidia_nim"
    assert resolved.provider_model == "fallback-model"
    assert resolved.provider_model_ref == "nvidia_nim/fallback-model"
    assert resolved.reasoning_preference is ReasoningPreference.CLIENT


def test_model_router_applies_opus_override(settings):
    settings.model_opus = "open_router/deepseek/deepseek-r1"

    request = MessagesRequest(
        model="claude-opus-4-20250514",
        max_tokens=100,
        messages=[Message(role="user", content="hello")],
    )
    routed = ModelRouter(settings).resolve_messages_request(request)

    assert routed.request.model == "deepseek/deepseek-r1"
    assert routed.resolved.provider_model_ref == "open_router/deepseek/deepseek-r1"
    assert routed.resolved.original_model == "claude-opus-4-20250514"
    assert routed.reasoning.control is ReasoningControl.DEFAULT
    assert request.model == "claude-opus-4-20250514"


def test_model_router_accepts_ultracode_in_local_fcc(settings):
    settings.reasoning_policy = ReasoningPreference.ULTRACODE
    request = MessagesRequest(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[Message(role="user", content="hello")],
    )

    routed = ModelRouter(settings).resolve_messages_request(request)

    assert routed.reasoning.effort is ReasoningEffort.XHIGH
    assert routed.reasoning.control is ReasoningControl.ON


def test_model_router_maps_client_ultracode_in_local_fcc(settings):
    request = MessagesRequest(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[Message(role="user", content="hello")],
        output_config={"effort": "ultracode"},
    )

    routed = ModelRouter(settings).resolve_messages_request(request)
    assert routed.reasoning.effort is ReasoningEffort.XHIGH


def test_model_router_applies_fable_override(settings):
    settings.model_fable = "open_router/anthropic/claude-fable-5"

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="claude-fable-5",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "anthropic/claude-fable-5"
    assert routed.resolved.provider_model_ref == "open_router/anthropic/claude-fable-5"
    assert routed.resolved.original_model == "claude-fable-5"


def test_model_router_resolves_route_reasoning_preferences(settings):
    settings.reasoning_policy = ReasoningPreference.OFF
    settings.reasoning_fable = ReasoningPreference.HIGH
    settings.reasoning_opus = ReasoningPreference.MAX
    settings.reasoning_haiku = ReasoningPreference.OFF

    router = ModelRouter(settings)

    assert (
        router.resolve("claude-fable-5").reasoning_preference
        is ReasoningPreference.HIGH
    )
    assert (
        router.resolve("claude-opus-4-20250514").reasoning_preference
        is ReasoningPreference.MAX
    )
    assert (
        router.resolve("claude-sonnet-4-20250514").reasoning_preference
        is ReasoningPreference.OFF
    )
    assert (
        router.resolve("claude-3-haiku-20240307").reasoning_preference
        is ReasoningPreference.OFF
    )
    assert router.resolve("claude-2.1").reasoning_preference is ReasoningPreference.OFF


def test_model_router_applies_haiku_override(settings):
    settings.model_haiku = "lmstudio/qwen2.5-7b"

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "qwen2.5-7b"
    assert routed.resolved.provider_model_ref == "lmstudio/qwen2.5-7b"


def test_model_router_applies_sonnet_override(settings):
    settings.model_sonnet = "nvidia_nim/meta/llama-3.3-70b-instruct"

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "meta/llama-3.3-70b-instruct"
    assert (
        routed.resolved.provider_model_ref == "nvidia_nim/meta/llama-3.3-70b-instruct"
    )


def test_model_router_routes_prefixed_provider_model_directly(settings):
    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="deepseek/deepseek-chat",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "deepseek-chat"
    assert routed.resolved.original_model == "deepseek/deepseek-chat"
    assert routed.resolved.provider_id == "deepseek"
    assert routed.resolved.provider_model == "deepseek-chat"
    assert routed.resolved.provider_model_ref == "deepseek/deepseek-chat"


def test_model_router_routes_explicit_opencode_zen_prefix(settings):
    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="opencode_zen/kimi-k2.6",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "kimi-k2.6"
    assert routed.resolved.provider_id == "opencode_zen"
    assert routed.resolved.provider_model_ref == "opencode_zen/kimi-k2.6"


def test_model_router_resolves_alias_before_provider_dispatch(settings):
    settings.model_aliases = "muse=opencode_go/minimax-m2.7"

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="muse",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "minimax-m2.7"
    assert routed.resolved.original_model == "muse"
    assert routed.resolved.provider_id == "opencode_go"
    assert routed.resolved.provider_model_ref == "opencode_go/minimax-m2.7"


def test_model_router_strips_virtual_context_suffix_before_provider_dispatch(settings):
    settings.model = "opencode_go/muse-spark-1.2-contributor[1m]"

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="claude-fable-5[1m]",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "muse-spark-1.2-contributor"
    assert routed.resolved.provider_model_ref == (
        "opencode_go/muse-spark-1.2-contributor"
    )
    assert routed.resolved.virtual_context_window == 1_000_000


def test_model_router_applies_manual_context_window_without_suffix(settings):
    settings = settings.model_copy(
        update={"model_context_windows": '{"nvidia_nim/fallback-model": 1000000}'}
    )

    resolved = ModelRouter(settings).resolve("claude-2.1")

    assert resolved.virtual_context_window == 1_000_000


def test_model_router_explicit_suffix_wins_over_manual_context_window(settings):
    settings = settings.model_copy(
        update={"model_context_windows": '{"nvidia_nim/fallback-model": 500000}'}
    )

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="claude-fable-5[1m]",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.resolved.virtual_context_window == 1_000_000


def test_model_router_applies_manual_window_to_direct_provider_model(settings):
    settings = settings.model_copy(
        update={"model_context_windows": '{"deepseek/deepseek-chat": 500000}'}
    )

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="deepseek/deepseek-chat",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.resolved.virtual_context_window == 500_000


def test_model_router_keeps_parent_window_over_manual_child_window() -> None:
    settings = Settings().model_copy(
        update={
            "model": "opencode_go/parent-model",
            "model_haiku": "opencode_zen/stale-child-model",
            "subagent_model_inherit": True,
            "model_context_windows": '{"opencode_zen/stale-child-model": 1000000}',
        }
    )
    router = ModelRouter(settings)
    parent = router.resolve("openai/gpt-5.6-luna")

    child = router.resolve("claude-3-haiku-20240307", parent_route=parent)

    assert child.route_source == "parent_inherited"
    assert child.virtual_context_window == parent.virtual_context_window


def test_model_router_normalizes_alias_target_virtual_context_suffix(settings):
    settings.model_aliases = "deep=opencode_go/minimax-m2.7[200k]"

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="deep",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "minimax-m2.7"
    assert routed.resolved.provider_model_ref == "opencode_go/minimax-m2.7"
    assert routed.resolved.virtual_context_window == 200_000


def test_model_router_keeps_exact_provider_ref_independent_of_aliases(settings):
    settings.model_aliases = "opencode=opencode_go/minimax-m2.7"

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="opencode_zen/kimi-k2.6",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.resolved.provider_model_ref == "opencode_zen/kimi-k2.6"


def test_model_router_routes_wafer_provider_model_directly(settings):
    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="wafer/DeepSeek-V4-Pro",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "DeepSeek-V4-Pro"
    assert routed.resolved.provider_id == "wafer"
    assert routed.resolved.provider_model == "DeepSeek-V4-Pro"
    assert routed.resolved.provider_model_ref == "wafer/DeepSeek-V4-Pro"


def test_model_router_routes_minimax_provider_model_directly(settings):
    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="minimax/MiniMax-M3",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "MiniMax-M3"
    assert routed.resolved.provider_id == "minimax"
    assert routed.resolved.provider_model == "MiniMax-M3"
    assert routed.resolved.provider_model_ref == "minimax/MiniMax-M3"


def test_model_router_routes_gateway_encoded_provider_model_directly(settings):
    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="anthropic/nvidia_nim/deepseek-ai/deepseek-v4-pro",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "deepseek-ai/deepseek-v4-pro"
    assert (
        routed.resolved.original_model
        == "anthropic/nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )
    assert routed.resolved.provider_id == "nvidia_nim"
    assert routed.resolved.provider_model == "deepseek-ai/deepseek-v4-pro"
    assert (
        routed.resolved.provider_model_ref == "nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )


def test_model_router_routes_no_thinking_gateway_model_directly(settings):
    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="claude-3-freecc-no-thinking/nvidia_nim/deepseek-ai/deepseek-v4-pro",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "deepseek-ai/deepseek-v4-pro"
    assert (
        routed.resolved.original_model
        == "claude-3-freecc-no-thinking/nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )
    assert routed.resolved.provider_id == "nvidia_nim"
    assert routed.resolved.provider_model == "deepseek-ai/deepseek-v4-pro"
    assert routed.reasoning.control is ReasoningControl.OFF


def test_model_router_routes_ultra_gateway_model_with_ultracode_effort(settings):
    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="claude-3-freecc-ultra/nvidia_nim/deepseek-ai/deepseek-v4-pro",
            max_tokens=100,
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.request.model == "deepseek-ai/deepseek-v4-pro"
    assert (
        routed.resolved.original_model
        == "claude-3-freecc-ultra/nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )
    assert routed.resolved.provider_id == "nvidia_nim"
    assert routed.resolved.provider_model == "deepseek-ai/deepseek-v4-pro"
    assert (
        routed.resolved.provider_model_ref == "nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )
    assert routed.resolved.reasoning_preference is ReasoningPreference.ULTRACODE
    assert routed.reasoning.control is ReasoningControl.ON
    assert routed.reasoning.effort is ReasoningEffort.XHIGH


def test_ultra_gateway_model_id_round_trips_provider_ref():
    from free_claude_code.core.gateway_model_ids import (
        decode_gateway_model_id,
        ultra_gateway_model_id,
    )

    model_id = ultra_gateway_model_id("openai/gpt-5.6-luna")

    assert model_id == "claude-3-freecc-ultra/openai/gpt-5.6-luna"
    # Gateway protocol: discovery keeps ids containing "claude"/"anthropic".
    assert "claude" in model_id.lower() or "anthropic" in model_id.lower()
    decoded = decode_gateway_model_id(model_id)
    assert decoded is not None
    assert decoded.provider_id == "openai"
    assert decoded.provider_model == "gpt-5.6-luna"
    assert decoded.force_ultracode is True
    assert decoded.force_reasoning_off is False


def test_direct_provider_model_uses_root_policy_without_model_name_guessing(settings):
    settings.reasoning_policy = ReasoningPreference.LOW
    settings.reasoning_opus = ReasoningPreference.MAX

    routed = ModelRouter(settings).resolve_messages_request(
        MessagesRequest(
            model="open_router/anthropic/claude-opus-4",
            messages=[Message(role="user", content="hello")],
        )
    )

    assert routed.resolved.provider_id == "open_router"
    assert routed.resolved.provider_model == "anthropic/claude-opus-4"
    assert routed.reasoning.effort is ReasoningEffort.LOW


def test_model_router_routes_token_count_request(settings):
    settings.model_haiku = "lmstudio/qwen2.5-7b"

    request = TokenCountRequest(
        model="claude-3-haiku-20240307",
        messages=[Message(role="user", content="hello")],
    )
    routed = ModelRouter(settings).resolve_token_count_request(request)

    assert routed.request.model == "qwen2.5-7b"
    assert request.model == "claude-3-haiku-20240307"


def test_model_router_logs_mapping(settings):
    with patch("free_claude_code.application.routing.logger.debug") as mock_log:
        ModelRouter(settings).resolve("claude-2.1")

    mock_log.assert_called()
    args = mock_log.call_args[0]
    assert "MODEL MAPPING" in args[0]
    assert args[1] == "claude-2.1"
    assert args[2] == "fallback-model"


def test_model_router_preserves_typed_error_for_unknown_mapped_provider(settings):
    settings.model = "unknown/model"

    with pytest.raises(UnknownProviderError) as exc_info:
        ModelRouter(settings).resolve("claude-2.1")

    supported = "', '".join(PROVIDER_CATALOG)
    assert str(exc_info.value) == (
        f"Unknown provider_type: 'unknown'. Supported: '{supported}'"
    )


def test_model_router_inherits_parent_route_over_stale_child_tier() -> None:
    settings = Settings().model_copy(
        update={
            "model": "opencode_go/parent-model",
            "model_haiku": "opencode_zen/stale-child-model",
            "subagent_model_inherit": True,
        }
    )
    router = ModelRouter(settings)
    parent = router.resolve("openai/gpt-5.6-luna")

    child = router.resolve("claude-3-haiku-20240307", parent_route=parent)

    assert child.provider_id == parent.provider_id == "openai"
    assert child.provider_model == parent.provider_model == "gpt-5.6-luna"
    assert (
        child.provider_model_ref == parent.provider_model_ref == ("openai/gpt-5.6-luna")
    )
    assert child.reasoning_preference is parent.reasoning_preference
    assert child.route_source == "parent_inherited"


def test_model_router_resolves_parent_tier_before_inheritance_is_available() -> None:
    settings = Settings().model_copy(
        update={
            "model": "opencode_go/parent-model",
            "model_haiku": "opencode_zen/stale-child-model",
        }
    )

    resolved = ModelRouter(settings).resolve("claude-3-haiku-20240307")

    assert resolved.provider_model_ref == "opencode_zen/stale-child-model"
    assert resolved.route_source == "model_haiku"


def test_model_router_inherits_a_logical_parent_tier_route() -> None:
    settings = Settings().model_copy(
        update={
            "model": "opencode_go/base-model",
            "model_opus": "openai/parent-opus-model",
            "model_haiku": "opencode_zen/stale-child-model",
            "subagent_model_inherit": True,
        }
    )
    router = ModelRouter(settings)

    parent = router.resolve("claude-3-opus-20240229")
    child = router.resolve("claude-3-haiku-20240307", parent_route=parent)

    assert parent.provider_model_ref == "openai/parent-opus-model"
    assert child.provider_model_ref == parent.provider_model_ref
    assert child.provider_model == parent.provider_model
    assert child.route_source == "parent_inherited"


def test_model_router_can_explicitly_restore_independent_tier_routing() -> None:
    settings = Settings().model_copy(
        update={
            "model": "opencode_go/parent-model",
            "model_haiku": "opencode_zen/stale-child-model",
            "subagent_model_inherit": False,
        }
    )

    router = ModelRouter(settings)
    parent = router.resolve("openai/gpt-5.6-luna")
    resolved = router.resolve(
        "claude-3-haiku-20240307",
        parent_route=parent,
    )

    assert resolved.provider_model_ref == "opencode_zen/stale-child-model"
    assert resolved.route_source == "model_haiku"


def test_parent_route_registry_is_generation_scoped_and_does_not_get_poisoned() -> None:
    registry = ParentRouteRegistry(max_entries=2)
    parent = ResolvedModel(
        original_model="openai/gpt-5.6-luna",
        provider_id="openai",
        provider_model="gpt-5.6-luna",
        provider_model_ref="openai/gpt-5.6-luna",
        reasoning_preference=ReasoningPreference.CLIENT,
    )
    child_override = ResolvedModel(
        original_model="openai/gpt-5.6-mini",
        provider_id="openai",
        provider_model="gpt-5.6-mini",
        provider_model_ref="openai/gpt-5.6-mini",
        reasoning_preference=ReasoningPreference.CLIENT,
    )

    registry.remember(" session-a ", parent, generation_id=7)
    registry.remember("session-a", child_override, generation_id=7)

    assert registry.lookup("session-a", generation_id=7) is parent
    assert registry.lookup("session-a", generation_id=8) is None


def test_parent_route_registry_evicts_oldest_entry() -> None:
    registry = ParentRouteRegistry(max_entries=1)
    route = ResolvedModel(
        original_model="opencode_go/model",
        provider_id="opencode_go",
        provider_model="model",
        provider_model_ref="opencode_go/model",
        reasoning_preference=ReasoningPreference.CLIENT,
    )

    registry.remember("first", route, generation_id=1)
    registry.remember("second", route, generation_id=1)

    assert registry.lookup("first", generation_id=1) is None
    assert registry.lookup("second", generation_id=1) is route


def test_model_router_routes_enabled_custom_provider_directly(settings):
    custom_settings = settings.model_copy(
        update={
            "custom_providers_json": (
                '{"providers":[{"id":"custom-lane","display_name":"Custom Lane",'
                '"base_url":"http://localhost:9000/v1","local":true,'
                '"models":["model-x"],"enabled":true}]}'
            )
        }
    )
    router = ModelRouter(custom_settings)

    direct = router.resolve("custom_lane/model-x")
    gateway = router.resolve("anthropic/custom_lane/model-x")

    assert direct.provider_id == "custom_lane"
    assert direct.provider_model == "model-x"
    assert direct.provider_model_ref == "custom_lane/model-x"
    assert gateway.provider_id == "custom_lane"
    assert gateway.provider_model == "model-x"
    assert gateway.provider_model_ref == "custom_lane/model-x"


def test_gateway_model_uses_canonical_manual_context_window(settings):
    settings = settings.model_copy(
        update={
            "model_context_windows": (
                '{"nvidia_nim/deepseek-ai/deepseek-v4-pro": 777777}'
            )
        }
    )

    resolved = ModelRouter(settings).resolve(
        "anthropic/nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )

    assert resolved.provider_model_ref == "nvidia_nim/deepseek-ai/deepseek-v4-pro"
    assert resolved.virtual_context_window == 777_777
