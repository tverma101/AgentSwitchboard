from free_claude_code.config.model_labels import model_display_name


def test_model_display_name_preserves_id_and_prettifies_nested_vendor_slug():
    assert model_display_name("nvidia_nim/z-ai/glm-5.2") == "NVIDIA NIM · GLM 5.2"


def test_model_display_name_strips_only_claude_code_display_wrapper():
    assert (
        model_display_name("anthropic/opencode_go/deepseek-v4-flash")
        == "OpenCode Go · DeepSeek V4 Flash"
    )
