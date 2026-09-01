"""Claude-facing model registry labels must preserve route identity."""

from free_claude_code.api.model_catalog import (
    DISCOVERED_MODEL_CREATED_AT,
    ModelResponse,
    _disambiguate_registry_display_names,
)


def test_registry_disambiguates_identical_friendly_names_with_exact_ids() -> None:
    models = [
        ModelResponse(
            id="anthropic/open_router/openai/gpt-model",
            display_name="GPT Model",
            created_at=DISCOVERED_MODEL_CREATED_AT,
        ),
        ModelResponse(
            id="anthropic/opencode/openai/gpt-model",
            display_name="GPT Model",
            created_at=DISCOVERED_MODEL_CREATED_AT,
        ),
    ]

    _disambiguate_registry_display_names(models)

    labels = [model.display_name for model in models]
    assert len(set(labels)) == 2
    assert models[0].id in models[0].display_name
    assert models[1].id in models[1].display_name
