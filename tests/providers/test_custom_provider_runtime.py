"""Runtime contracts for custom OpenAI-compatible endpoints."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from free_claude_code.config.settings import Settings
from free_claude_code.providers.openai_chat import OpenAIChatProvider
from free_claude_code.providers.runtime import create_provider


def _settings() -> Settings:
    raw = json.dumps(
        {
            "providers": [
                {
                    "id": "remote-one",
                    "display_name": "Remote One",
                    "base_url": "https://one.example.test/v1",
                    "api_key": "secret-one",
                    "models": ["one/fallback"],
                },
                {
                    "id": "local-two",
                    "display_name": "Local Two",
                    "base_url": "http://localhost:8080/v1",
                    "local": True,
                    "models": ["two/fallback"],
                },
            ]
        }
    )
    return Settings(
        model="remote_one/one/fallback",
        CUSTOM_PROVIDERS_JSON=raw,
        voice_note_enabled=False,
    )


def test_factory_uses_shared_openai_adapter_for_custom_provider() -> None:
    with patch("free_claude_code.providers.openai_chat.provider.AsyncOpenAI"):
        provider = create_provider("remote_one", _settings())

    assert isinstance(provider, OpenAIChatProvider)
    assert provider._config.api_key == "secret-one"
    assert provider._config.base_url == "https://one.example.test/v1"
    assert provider._profile.provider_name == "CUSTOM_PROVIDER:remote_one"


@pytest.mark.asyncio
async def test_explicit_model_ids_are_used_when_model_discovery_is_unavailable() -> (
    None
):
    with patch("free_claude_code.providers.openai_chat.provider.AsyncOpenAI"):
        provider = create_provider("local_two", _settings())
    assert isinstance(provider, OpenAIChatProvider)
    provider._list_models_payload = AsyncMock(side_effect=RuntimeError("offline"))

    infos = await provider.list_model_infos()

    assert {info.model_id for info in infos} == {"two/fallback"}


def test_custom_provider_proxy_is_carried_by_shared_provider_config() -> None:
    settings = _settings().model_copy(
        update={
            "custom_providers_json": json.dumps(
                {
                    "providers": [
                        {
                            "id": "proxied",
                            "display_name": "Proxied",
                            "base_url": "https://proxy.example.test/v1",
                            "api_key": "secret",
                            "proxy": "http://proxy.example.test:3128",
                        }
                    ]
                }
            ),
            "model": "proxied/model",
        }
    )

    with patch("free_claude_code.providers.openai_chat.provider.AsyncOpenAI"):
        provider = create_provider("proxied", settings)

    assert provider._config.proxy == "http://proxy.example.test:3128"
