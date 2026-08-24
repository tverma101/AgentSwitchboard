from fastapi.testclient import TestClient

from free_claude_code.application.model_metadata import (
    CapabilityEvidence,
    CapabilityEvidenceStatus,
    ProviderModelInfo,
    ReasoningCapabilityEvidence,
    ReasoningCapabilityStatus,
)
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.settings import Settings
from tests.api.support import create_test_app, provider_manager_for_app


def _settings(
    *,
    model: str = "deepseek/deepseek-chat",
    model_fable: str | None = None,
    model_opus: str | None = "open_router/anthropic/claude-opus",
    model_haiku: str | None = "deepseek/deepseek-chat",
) -> Settings:
    return Settings.model_construct(
        model=model,
        model_fable=model_fable,
        model_opus=model_opus,
        model_sonnet=None,
        model_haiku=model_haiku,
        anthropic_auth_token="",
        deepseek_api_key="deepseek-key",
        open_router_api_key="open-router-key",
        wafer_api_key="wafer-key",
    )


def _cache_models(app, provider_id: str, *model_ids: str) -> None:
    provider_manager_for_app(app).cache_model_infos(
        provider_id,
        {ProviderModelInfo(model_id) for model_id in model_ids},
    )


def test_models_list_includes_configured_refs_cached_provider_models_and_aliases():
    app = create_test_app(_settings())
    _cache_models(app, "deepseek", "deepseek-chat")
    _cache_models(
        app,
        "open_router",
        "meta/llama-3.3",
        "anthropic/claude-opus",
    )

    response = TestClient(app).get("/v1/models")

    assert response.status_code == 200
    data = response.json()
    ids = [item["id"] for item in data["data"]]
    assert ids[:6] == [
        "anthropic/deepseek/deepseek-chat",
        "claude-3-freecc-no-thinking/deepseek/deepseek-chat",
        "anthropic/open_router/anthropic/claude-opus",
        "claude-3-freecc-no-thinking/open_router/anthropic/claude-opus",
        "anthropic/open_router/meta/llama-3.3",
        "claude-3-freecc-no-thinking/open_router/meta/llama-3.3",
    ]
    assert ids.count("anthropic/deepseek/deepseek-chat") == 1
    assert ids.count("anthropic/open_router/anthropic/claude-opus") == 1
    display_names = {item["id"]: item["display_name"] for item in data["data"]}
    assert (
        display_names["anthropic/open_router/meta/llama-3.3"]
        == "open_router/meta/llama-3.3"
    )
    assert (
        display_names["claude-3-freecc-no-thinking/open_router/meta/llama-3.3"]
        == "open_router/meta/llama-3.3 (no thinking)"
    )
    assert "claude-sonnet-4-20250514" in ids
    assert "claude-fable-5" in ids
    assert data["first_id"] == ids[0]
    assert data["last_id"] == ids[-1]
    assert data["has_more"] is False


def test_models_list_uses_thinking_metadata_for_cached_models():
    app = create_test_app(_settings(model_opus=None))
    manager = provider_manager_for_app(app)
    _cache_models(app, "deepseek", "deepseek-chat")
    manager.cache_model_infos(
        "open_router",
        {
            ProviderModelInfo("reasoning-model", supports_thinking=True),
            ProviderModelInfo("plain-model", supports_thinking=False),
        },
    )

    response = TestClient(app).get("/v1/models")

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert "anthropic/open_router/reasoning-model" in ids
    assert "claude-3-freecc-no-thinking/open_router/reasoning-model" in ids
    assert "anthropic/open_router/plain-model" not in ids
    assert "claude-3-freecc-no-thinking/open_router/plain-model" in ids


def test_models_list_uses_cached_metadata_for_configured_refs():
    app = create_test_app(
        _settings(
            model="open_router/plain-model",
            model_opus=None,
            model_haiku=None,
        )
    )
    provider_manager_for_app(app).cache_model_infos(
        "open_router",
        {ProviderModelInfo("plain-model", supports_thinking=False)},
    )

    response = TestClient(app).get("/v1/models")

    ids = [item["id"] for item in response.json()["data"]]
    assert "anthropic/open_router/plain-model" not in ids
    assert ids[0] == "claude-3-freecc-no-thinking/open_router/plain-model"


def test_models_list_exposes_cached_visual_metadata_for_configured_refs():
    app = create_test_app(
        _settings(
            model="open_router/vision-model",
            model_opus=None,
            model_haiku=None,
        )
    )
    provider_manager_for_app(app).cache_model_infos(
        "open_router",
        {
            ProviderModelInfo(
                "vision-model",
                supports_vision=True,
                accepted_image_types=("image/jpeg", "image/png"),
                capability_evidence=CapabilityEvidence(
                    statuses=(("vision_input", CapabilityEvidenceStatus.SUPPORTED),),
                    evidence_source="provider_metadata",
                    observed_at="2026-08-24T08:00:00Z",
                    evidence_version="catalog-v1",
                    evidence_protocol="responses",
                ),
            )
        },
    )

    response = TestClient(app).get("/v1/models")

    models = {item["id"]: item for item in response.json()["data"]}
    for model_id in (
        "anthropic/open_router/vision-model",
        "claude-3-freecc-no-thinking/open_router/vision-model",
    ):
        assert models[model_id]["supports_vision"] is True
        assert models[model_id]["accepted_image_types"] == [
            "image/jpeg",
            "image/png",
        ]
        assert models[model_id]["capability_evidence"] == {"vision_input": "supported"}
        assert models[model_id]["capability_evidence_source"] == "provider_metadata"
        assert models[model_id]["capability_evidence_observed_at"] == (
            "2026-08-24T08:00:00Z"
        )
        assert models[model_id]["capability_evidence_version"] == "catalog-v1"
        assert models[model_id]["capability_evidence_protocol"] == "responses"


def test_models_list_exposes_reasoning_capability_evidence() -> None:
    app = create_test_app(
        _settings(
            model="open_router/reasoning-model",
            model_opus=None,
            model_haiku=None,
        )
    )
    provider_manager_for_app(app).cache_model_infos(
        "open_router",
        {
            ProviderModelInfo(
                "reasoning-model",
                reasoning=ReasoningCapabilityEvidence(
                    status=ReasoningCapabilityStatus.SUPPORTED,
                    effort_evidence=(
                        ("low", ReasoningCapabilityStatus.SUPPORTED),
                        ("max", ReasoningCapabilityStatus.ACCEPTED_BUT_UNVERIFIED),
                    ),
                    provider_default_effort="low",
                    reports_reasoning_tokens=True,
                    emits_visible_summary=True,
                    emits_opaque_continuation=True,
                    evidence_source="deterministic_fixture",
                    evidence_protocol="responses",
                ),
            )
        },
    )

    response = TestClient(app).get("/v1/models")

    model = next(
        item
        for item in response.json()["data"]
        if item["id"] == "anthropic/open_router/reasoning-model"
    )
    assert model["reasoning_support"] == "supported"
    assert model["reasoning_effort_evidence"] == {
        "low": "supported",
        "max": "accepted-but-unverified",
    }
    assert model["reasoning_default_effort"] == "low"
    assert model["reasoning_tokens_reported"] is True
    assert model["reasoning_summary_emitted"] is True
    assert model["reasoning_opaque_continuation"] is True
    assert model["reasoning_evidence_source"] == "deterministic_fixture"
    assert model["reasoning_evidence_protocol"] == "responses"


def test_models_list_includes_cached_wafer_models():
    app = create_test_app(
        _settings(
            model="wafer/DeepSeek-V4-Pro",
            model_opus=None,
            model_haiku=None,
        )
    )
    _cache_models(app, "wafer", "DeepSeek-V4-Pro", "MiniMax-M2.7")

    response = TestClient(app).get("/v1/models")

    ids = [item["id"] for item in response.json()["data"]]
    assert "anthropic/wafer/DeepSeek-V4-Pro" in ids
    assert "claude-3-freecc-no-thinking/wafer/DeepSeek-V4-Pro" in ids
    assert "anthropic/wafer/MiniMax-M2.7" in ids
    assert "claude-3-freecc-no-thinking/wafer/MiniMax-M2.7" in ids


def test_models_list_works_with_empty_discovery_catalog():
    app = create_test_app(_settings())

    response = TestClient(app).get("/v1/models")

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert ids[:4] == [
        "anthropic/deepseek/deepseek-chat",
        "claude-3-freecc-no-thinking/deepseek/deepseek-chat",
        "anthropic/open_router/anthropic/claude-opus",
        "claude-3-freecc-no-thinking/open_router/anthropic/claude-opus",
    ]
    assert "claude-sonnet-4-20250514" in ids


def test_models_list_refilters_cached_catalog_after_policy_edit_and_keeps_configured_ref():
    settings = _settings(
        model="open_router/unknown-configured-model",
        model_opus=None,
        model_haiku=None,
    )
    settings.model_catalog_mode = ModelCatalogMode.CURATED
    settings.model_catalog_allowlist = "open_router/visible-model"
    app = create_test_app(settings)
    _cache_models(app, "open_router", "visible-model", "hidden-model")

    response = TestClient(app).get("/v1/models")

    assert response.status_code == 200
    ids = [item["display_name"] for item in response.json()["data"]]
    assert "open_router/unknown-configured-model" in ids
    assert "open_router/visible-model" in ids
    assert "open_router/hidden-model" not in ids

    settings.model_catalog_mode = ModelCatalogMode.ALL
    response = TestClient(app).get("/v1/models")

    ids = [item["display_name"] for item in response.json()["data"]]
    assert "open_router/hidden-model" in ids


def test_models_list_exposes_stable_aliases_without_replacing_exact_refs():
    settings = _settings(model_opus=None, model_haiku=None)
    settings.model_aliases = "muse=opencode_go/minimax-m2.7"
    app = create_test_app(settings)

    response = TestClient(app).get("/v1/models")

    aliases = {
        item["id"]: item["display_name"]
        for item in response.json()["data"]
        if item["id"] == "muse"
    }
    assert aliases == {"muse": "muse → opencode_go/minimax-m2.7"}


def test_models_list_propagates_alias_target_visual_metadata():
    settings = _settings(model_opus=None, model_haiku=None)
    settings.model_aliases = "muse=open_router/vision-model"
    app = create_test_app(settings)
    provider_manager_for_app(app).cache_model_infos(
        "open_router",
        {
            ProviderModelInfo(
                "vision-model",
                supports_vision=True,
                accepted_image_types=("image/png",),
            )
        },
    )

    response = TestClient(app).get("/v1/models")

    alias = next(item for item in response.json()["data"] if item["id"] == "muse")
    assert alias["supports_vision"] is True
    assert alias["accepted_image_types"] == ["image/png"]


def test_known_nonvision_model_rejects_image_before_provider_resolution():
    app = create_test_app(_settings(model_opus=None, model_haiku=None))
    manager = provider_manager_for_app(app)
    manager.cache_model_infos(
        "deepseek",
        {ProviderModelInfo("deepseek-chat", supports_vision=False)},
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/messages",
            json={
                "model": "deepseek/deepseek-chat",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "url",
                                    "url": "https://example.test/image.png",
                                },
                            }
                        ],
                    }
                ],
                "max_tokens": 8,
            },
        )

    assert response.status_code == 400
    assert "image input" in response.json()["error"]["message"]
