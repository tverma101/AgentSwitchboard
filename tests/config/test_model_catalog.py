from free_claude_code.config.model_catalog import (
    ModelCatalogMode,
    ModelCatalogPolicy,
    normalize_model_ref,
    parse_model_catalog_allowlist,
)


def test_parse_allowlist_accepts_commas_newlines_and_wildcards() -> None:
    assert parse_model_catalog_allowlist(
        "opencode_zen/muse-spark-1.2-contributor-free,\n"
        "opencode_go/minimax-m2.7\r\nopencode_go/*"
    ) == frozenset(
        {
            "opencode_zen/muse-spark-1.2-contributor-free",
            "opencode_go/minimax-m2.7",
            "opencode_go/*",
        }
    )


def test_all_mode_exposes_every_discovered_model() -> None:
    policy = ModelCatalogPolicy(mode=ModelCatalogMode.ALL)

    assert policy.is_visible("opencode_zen", "muse-spark-1.2-contributor-free")
    assert policy.is_visible("opencode_go", "minimax-m2.7")


def test_curated_mode_hides_unlisted_models() -> None:
    policy = ModelCatalogPolicy(
        mode=ModelCatalogMode.CURATED,
        allowlist=frozenset({"opencode_zen/muse-spark-1.2-contributor-free"}),
    )

    assert policy.is_visible("opencode_zen", "muse-spark-1.2-contributor-free")
    assert not policy.is_visible("opencode_zen", "mimo-v2.5-free")
    assert not policy.is_visible("opencode_go", "minimax-m2.7")


def test_provider_wildcard_exposes_only_that_provider() -> None:
    policy = ModelCatalogPolicy(
        mode=ModelCatalogMode.CURATED,
        allowlist=frozenset({"opencode_go/*"}),
    )

    assert policy.is_visible("opencode_go", "minimax-m2.7")
    assert not policy.is_visible("opencode_zen", "minimax-m2.7")


def test_global_wildcard_exposes_every_provider_in_curated_mode() -> None:
    policy = ModelCatalogPolicy(
        mode=ModelCatalogMode.CURATED,
        allowlist=frozenset({"*"}),
    )

    assert policy.is_visible("opencode_go", "anything")
    assert policy.is_visible("nvidia_nim", "anything")


def test_already_prefixed_cached_ref_normalizes_without_duplication() -> None:
    assert (
        normalize_model_ref("opencode_go", "opencode_go/minimax-m2.7")
        == "opencode_go/minimax-m2.7"
    )
