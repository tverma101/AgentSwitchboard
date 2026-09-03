"""Regressions for FCC models appearing in Claude Code's gateway picker."""

from typing import cast

from free_claude_code.api.model_catalog import build_models_list_response
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.application.ports import RequestRuntimePort
from free_claude_code.cli.claude_env import build_claude_proxy_env
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.model_labels import model_display_name
from free_claude_code.config.settings import Settings
from free_claude_code.core.gateway_model_ids import gateway_model_id

MODEL_A = "open_router/provider/alpha"
MODEL_B = "open_router/provider/beta"


class _CachedRuntime:
    def __init__(self, *model_refs: str) -> None:
        self._infos = tuple(ProviderModelInfo(model_id=ref) for ref in model_refs)

    def cached_model_info(
        self, provider_id: str, model_id: str
    ) -> ProviderModelInfo | None:
        model_ref = f"{provider_id}/{model_id}"
        return next(
            (info for info in self._infos if info.model_id == model_ref),
            None,
        )

    def cached_prefixed_model_infos(self) -> tuple[ProviderModelInfo, ...]:
        return self._infos


def _settings(allowlist: str, *, model: str = MODEL_A) -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        anthropic_auth_token="freecc",
        model=model,
        model_fable=None,
        model_opus=None,
        model_sonnet=None,
        model_haiku=None,
        model_aliases="",
        model_catalog_mode=ModelCatalogMode.CURATED,
        model_catalog_allowlist=allowlist,
        nvidia_nim_model_allowlist="",
    )


def test_claude_proxy_env_enters_gateway_mode_for_model_discovery() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="freecc",
        base_env={},
        process_wrapper_path="/tmp/fcc-wrapper",
    )

    assert env["CLAUDE_CODE_USE_GATEWAY"] == "1"
    assert env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"


def test_enabling_cached_picker_model_adds_it_to_claude_registry_with_name() -> None:
    runtime = cast(RequestRuntimePort, _CachedRuntime(MODEL_A, MODEL_B))

    hidden = build_models_list_response(_settings(MODEL_A), runtime)
    hidden_ids = {model.id for model in hidden.data}
    assert gateway_model_id(MODEL_B) not in hidden_ids

    enabled = build_models_list_response(_settings(f"{MODEL_A}, {MODEL_B}"), runtime)
    beta = next(
        model for model in enabled.data if model.id == gateway_model_id(MODEL_B)
    )

    assert beta.display_name == model_display_name(MODEL_B)
    assert beta.display_name != MODEL_B


def test_maximum_reasoning_variant_does_not_claim_native_ultracode() -> None:
    runtime = cast(RequestRuntimePort, _CachedRuntime(MODEL_A))

    response = build_models_list_response(_settings(MODEL_A), runtime)

    maximum_reasoning = next(
        model
        for model in response.data
        if model.id.startswith("claude-3-freecc-ultra/")
    )
    assert maximum_reasoning.display_name == (
        f"{model_display_name(MODEL_A)} (maximum reasoning)"
    )
    assert "ultracode" not in maximum_reasoning.display_name.lower()


def test_registry_does_not_retain_dynamic_label_disambiguation() -> None:
    runtime = cast(RequestRuntimePort, _CachedRuntime())

    colliding = build_models_list_response(
        _settings(
            "anthropic/claude-opus-4",
            model="anthropic/claude-opus-4",
        ),
        runtime,
    )
    colliding_static = next(
        model for model in colliding.data if model.id == "claude-opus-4-20250514"
    )
    assert colliding_static.display_name == ("Claude Opus 4 [claude-opus-4-20250514]")

    later = build_models_list_response(_settings(MODEL_A), runtime)
    later_static = next(
        model for model in later.data if model.id == "claude-opus-4-20250514"
    )

    assert later_static.display_name == "Claude Opus 4"
