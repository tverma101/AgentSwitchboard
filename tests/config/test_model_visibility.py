from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.config.model_visibility import (
    filter_cached_model_infos,
    filter_discovered_model_infos,
    parse_nvidia_nim_model_allowlist,
)
from free_claude_code.config.settings import Settings


def _settings(allowlist: str) -> Settings:
    return Settings.model_construct(nvidia_nim_model_allowlist=allowlist)


def test_nim_allowlist_accepts_full_refs_and_newlines() -> None:
    assert parse_nvidia_nim_model_allowlist(
        "nvidia_nim/z-ai/glm-5.2,\nnvidia/nemotron-3-super-120b-a12b"
    ) == frozenset({"z-ai/glm-5.2", "nvidia/nemotron-3-super-120b-a12b"})


def test_empty_nim_allowlist_hides_discovered_models() -> None:
    settings = _settings("")

    assert (
        filter_discovered_model_infos(
            settings,
            "nvidia_nim",
            {
                ProviderModelInfo("z-ai/glm-5.2"),
                ProviderModelInfo("nvidia/nemotron-3-super-120b-a12b"),
            },
        )
        == frozenset()
    )


def test_nim_allowlist_keeps_other_providers_and_selected_models() -> None:
    settings = _settings("z-ai/glm-5.2")
    cached = (
        ProviderModelInfo("nvidia_nim/z-ai/glm-5.2"),
        ProviderModelInfo("nvidia_nim/nvidia/nemotron-3-super-120b-a12b"),
        ProviderModelInfo("opencode_go/glm-5.2"),
    )

    assert filter_cached_model_infos(settings, cached) == (
        ProviderModelInfo("nvidia_nim/z-ai/glm-5.2"),
        ProviderModelInfo("opencode_go/glm-5.2"),
    )


def test_nim_wildcard_exposes_all_discovered_models() -> None:
    settings = _settings("*")
    infos = {ProviderModelInfo("nvidia/model-a"), ProviderModelInfo("nvidia/model-b")}

    assert filter_discovered_model_infos(settings, "nvidia_nim", infos) == infos
