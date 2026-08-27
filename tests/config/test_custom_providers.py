"""Contracts for user-defined OpenAI-compatible provider configuration."""

import json
from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from free_claude_code.config.custom_providers import (
    CUSTOM_PROVIDERS_ENV,
    parse_custom_provider_json,
    provider_registry_from_json,
    public_custom_provider_status,
    remove_custom_provider_json,
    sanitize_provider_id,
    serialize_custom_providers,
    update_custom_provider_json,
)
from free_claude_code.config.provider_catalog import PROVIDER_CATALOG
from free_claude_code.config.settings import Settings


def _document(*providers: dict[str, object]) -> str:
    return json.dumps({"providers": list(providers)})


def _remote(**overrides: object) -> dict[str, object]:
    return {
        "id": "Acme Gateway",
        "display_name": "Acme Gateway",
        "base_url": "https://api.example.test/v1",
        "api_key": "remote-secret",
        "models": ["acme/model-a"],
        **overrides,
    }


def test_provider_id_is_sanitized_and_bounded() -> None:
    assert sanitize_provider_id(" Acme Gateway v2 ") == "acme_gateway_v2"
    assert sanitize_provider_id("123-gateway") == "custom_123_gateway"
    with pytest.raises(ValueError, match="letter or number"):
        sanitize_provider_id("---")
    with pytest.raises(ValueError, match="at most"):
        sanitize_provider_id("a" * 41)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"base_url": "http://api.example.test/v1"}, "HTTPS"),
        ({"base_url": "https://user:pass@example.test/v1"}, "credentials"),
        ({"base_url": "ftp://api.example.test/v1"}, "http or https"),
        ({"base_url": "https://api.example.test/v1?token=secret"}, "query"),
        ({"base_url": "https://127.0.0.1:9999/v1"}, "local=True"),
        (
            {"base_url": "https://api.example.test/v1", "api_key": ""},
            "requires an API key",
        ),
    ),
)
def test_remote_descriptor_fails_closed(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_custom_provider_json(_document(_remote(**overrides)))


def test_loopback_descriptor_can_omit_key_but_requires_local_classification() -> None:
    provider = parse_custom_provider_json(
        _document(
            _remote(
                id="local-gateway",
                display_name="Local Gateway",
                base_url="http://127.0.0.1:8080/v1",
                api_key="",
                local=True,
                models=["local/model"],
            )
        )
    )[0]

    assert provider.local is True
    assert provider.api_key == ""
    with pytest.raises(ValueError, match="local=True"):
        parse_custom_provider_json(
            _document(
                _remote(
                    id="local-gateway",
                    base_url="http://127.0.0.1:8080/v1",
                    api_key="",
                )
            )
        )


def test_registry_composes_without_mutating_builtins() -> None:
    raw = _document(
        _remote(id="zeta", display_name="Zeta"),
        _remote(id="alpha", display_name="Alpha"),
    )
    registry = provider_registry_from_json(raw)

    assert tuple(registry.custom) == ("alpha", "zeta")
    assert registry.order[-2:] == ("alpha", "zeta")
    assert set(PROVIDER_CATALOG).isdisjoint(registry.custom)
    with pytest.raises(TypeError):
        cast(Any, registry.catalog)["new"] = PROVIDER_CATALOG["openai"]


def test_disabled_provider_is_not_in_runtime_registry_but_remains_visible() -> None:
    raw = _document(_remote(id="disabled", enabled=False))

    registry = provider_registry_from_json(raw)
    public = public_custom_provider_status(raw)

    assert "disabled" not in registry.catalog
    assert public[0]["enabled"] is False
    assert "api_key" not in public[0]
    assert "remote-secret" not in repr(public[0])


def test_duplicate_and_builtin_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        parse_custom_provider_json(_document(_remote(id="same"), _remote(id="same")))
    with pytest.raises(ValueError, match="collides with built-in"):
        parse_custom_provider_json(_document(_remote(id="openai")))


def test_unknown_descriptor_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="headers"):
        parse_custom_provider_json(_document(_remote(headers={"x": "y"})))


def test_serialization_is_deterministic_and_update_preserves_hidden_key() -> None:
    raw = _document(_remote(id="gateway", display_name="Gateway"))
    updated = update_custom_provider_json(
        raw,
        {"display_name": "Gateway Two", "models": ["model-b"]},
        existing_provider_id="gateway",
    )
    descriptor = parse_custom_provider_json(updated)[0]

    assert descriptor.display_name == "Gateway Two"
    assert descriptor.api_key == "remote-secret"
    assert updated == serialize_custom_providers((descriptor,))
    assert remove_custom_provider_json(updated, "gateway") == '{"providers":[]}'


def test_settings_accepts_enabled_custom_provider_model_reference() -> None:
    settings = Settings(
        model="acme_gateway/acme/model-a",
        CUSTOM_PROVIDERS_JSON=_document(_remote()),
        voice_note_enabled=False,
    )

    assert settings.model == "acme_gateway/acme/model-a"


def test_settings_rejects_custom_model_reference_when_provider_disabled() -> None:
    with pytest.raises(ValueError, match="Invalid provider"):
        Settings(
            model="disabled/model",
            CUSTOM_PROVIDERS_JSON=_document(_remote(id="disabled", enabled=False)),
            voice_note_enabled=False,
        )


def test_custom_provider_descriptor_does_not_expose_secrets_in_repr() -> None:
    descriptor = parse_custom_provider_json(_document(_remote()))[0]

    assert "remote-secret" not in repr(descriptor)
    with pytest.raises(FrozenInstanceError):
        descriptor.__setattr__("display_name", "changed")


def test_custom_provider_env_name_is_the_admin_persistence_boundary() -> None:
    assert CUSTOM_PROVIDERS_ENV == "CUSTOM_PROVIDERS_JSON"
