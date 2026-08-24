from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.model_visibility import (
    filter_cached_model_infos,
    filter_discovered_model_infos,
    is_discovered_model_visible,
    model_catalog_policy_for_settings,
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


def test_generic_all_mode_overrides_legacy_nim_filter() -> None:
    settings = Settings.model_construct(
        model_catalog_mode=ModelCatalogMode.ALL,
        model_catalog_allowlist="",
        nvidia_nim_model_allowlist="",
    )

    assert model_catalog_policy_for_settings(settings) is not None
    assert is_discovered_model_visible(settings, "nvidia_nim", "hidden-by-legacy")
    assert is_discovered_model_visible(settings, "opencode_go", "minimax-m2.7")


def test_generic_curated_mode_uses_full_refs_and_overrides_legacy_nim_filter() -> None:
    settings = Settings.model_construct(
        model_catalog_mode=ModelCatalogMode.CURATED,
        model_catalog_allowlist="opencode_go/*",
        nvidia_nim_model_allowlist="*",
    )

    assert is_discovered_model_visible(settings, "opencode_go", "minimax-m2.7")
    assert not is_discovered_model_visible(settings, "nvidia_nim", "nvidia/nemotron")


def test_allowlist_without_mode_implies_curated_generic_policy() -> None:
    settings = Settings.model_construct(
        model_catalog_mode=None,
        model_catalog_allowlist="opencode_zen/muse-spark",
        nvidia_nim_model_allowlist="*",
    )

    assert is_discovered_model_visible(settings, "opencode_zen", "muse-spark")
    assert not is_discovered_model_visible(settings, "opencode_go", "minimax-m2.7")


def test_missing_generic_settings_retain_legacy_nim_behavior() -> None:
    settings = _settings("nim-visible")

    assert is_discovered_model_visible(settings, "nvidia_nim", "nim-visible")
    assert not is_discovered_model_visible(settings, "nvidia_nim", "nim-hidden")
    assert is_discovered_model_visible(settings, "opencode_go", "minimax-m2.7")
