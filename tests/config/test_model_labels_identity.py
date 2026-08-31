"""Model labels must remain readable without collapsing route identity."""

from free_claude_code.config.model_labels import model_display_names


def test_nested_gpt_routes_get_collision_free_labels() -> None:
    refs = {
        "open_router/openai/gpt-model",
        "opencode/openai/gpt-model",
        "opencode_go/openai/gpt-model",
        "open_router/openai/gpt-model:free",
        "open_router/azure/gpt-model",
        "openai/gpt-model",
    }

    labels = model_display_names(refs)

    assert len(labels) == 6
    assert len({label.casefold() for label in labels.values()}) == 6
    assert "[open_router/openai/gpt-model]" in labels["open_router/openai/gpt-model"]
    assert "[open_router/azure/gpt-model]" in labels["open_router/azure/gpt-model"]
