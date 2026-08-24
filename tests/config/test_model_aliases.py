import pytest

from free_claude_code.config.model_aliases import (
    ModelAliasError,
    parse_model_aliases,
)


def test_aliases_parse_from_newlines_and_commas() -> None:
    aliases = parse_model_aliases(
        "coding-default=opencode_zen/muse-spark-1.2-contributor-free\n"
        "coding-fast=opencode_go/minimax-m2.7"
    )

    assert (
        aliases.resolve("coding-default")
        == "opencode_zen/muse-spark-1.2-contributor-free"
    )
    assert aliases.resolve("coding-fast") == "opencode_go/minimax-m2.7"


def test_exact_provider_model_bypasses_alias_lookup() -> None:
    aliases = parse_model_aliases("coding-fast=opencode_go/minimax-m2.7")

    assert (
        aliases.resolve("opencode_zen/muse-spark-1.2-contributor-free")
        == "opencode_zen/muse-spark-1.2-contributor-free"
    )


def test_unknown_alias_is_explicit_error() -> None:
    aliases = parse_model_aliases("coding-fast=opencode_go/minimax-m2.7")

    with pytest.raises(ModelAliasError, match="unknown model alias"):
        aliases.resolve("coding-deep")


def test_alias_target_must_be_exact_provider_ref() -> None:
    with pytest.raises(ModelAliasError, match="provider/model"):
        parse_model_aliases("coding-default=another-alias")


def test_alias_name_must_not_look_like_provider_ref() -> None:
    with pytest.raises(ModelAliasError, match="must not contain"):
        parse_model_aliases("opencode_go/default=opencode_go/minimax-m2.7")


def test_duplicate_alias_is_rejected() -> None:
    with pytest.raises(ModelAliasError, match="duplicate model alias"):
        parse_model_aliases(
            "default=opencode_go/minimax-m2.7,"
            "default=opencode_zen/muse-spark-1.2-contributor-free"
        )
