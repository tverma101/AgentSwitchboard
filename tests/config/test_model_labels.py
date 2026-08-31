from free_claude_code.config.model_labels import (
    model_display_name,
    model_display_names,
)


def test_model_display_name_preserves_nested_vendor_slug() -> None:
    assert (
        model_display_name("nvidia_nim/z-ai/glm-5.2")
        == "NVIDIA NIM · GLM 5.2 [z-ai/glm-5.2]"
    )


def test_model_display_name_strips_only_claude_code_display_wrapper() -> None:
    assert (
        model_display_name("anthropic/opencode_go/deepseek-v4-flash")
        == "OpenCode Go · DeepSeek V4 Flash"
    )


def test_nested_models_with_same_leaf_never_collapse_to_same_name() -> None:
    refs = {
        "open_router/openai/gpt-model",
        "open_router/azure/gpt-model",
        "open_router/custom/gpt-model",
    }

    labels = model_display_names(refs)

    assert len(set(labels.values())) == len(refs)
    assert "[openai/gpt-model]" in labels["open_router/openai/gpt-model"]
    assert "[azure/gpt-model]" in labels["open_router/azure/gpt-model"]
    assert "[custom/gpt-model]" in labels["open_router/custom/gpt-model"]


def test_batch_labels_disambiguate_wrapper_collisions() -> None:
    refs = {
        "open_router/openai/gpt-model",
        "anthropic/open_router/openai/gpt-model",
    }

    labels = model_display_names(refs)

    assert len(set(labels.values())) == 2
    assert labels["open_router/openai/gpt-model"] != labels[
        "anthropic/open_router/openai/gpt-model"
    ]
