from unittest.mock import patch

import pytest
from pydantic import ValidationError

from free_claude_code.config.settings import Settings


@pytest.fixture(autouse=True)
def clear_server_auth_env(monkeypatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("HOST", raising=False)


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "127.0.0.42", "::1", "[::1]", "localhost"]
)
def test_loopback_server_may_run_without_proxy_token(host: str) -> None:
    with patch(
        "free_claude_code.config.settings.env_file_override",
        return_value=None,
    ):
        settings = Settings(host=host, voice_note_enabled=False)
    assert settings.host == host
    assert settings.anthropic_auth_token == ""


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "::", "192.168.1.10", "proxy.example.test"]
)
def test_non_loopback_server_requires_proxy_token(host: str) -> None:
    with (
        patch(
            "free_claude_code.config.settings.env_file_override",
            return_value=None,
        ),
        pytest.raises(ValidationError, match="ANTHROPIC_AUTH_TOKEN is required"),
    ):
        Settings(host=host, voice_note_enabled=False)


def test_non_loopback_server_accepts_environment_proxy_token(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")
    with patch(
        "free_claude_code.config.settings.env_file_override",
        return_value=None,
    ):
        settings = Settings(host="0.0.0.0", voice_note_enabled=False)
    assert settings.host == "0.0.0.0"
    assert settings.anthropic_auth_token == "test-token"


def test_managed_empty_token_rejects_non_loopback_bind(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "process-token")
    with (
        patch(
            "free_claude_code.config.settings.env_file_override",
            return_value="",
        ),
        pytest.raises(ValidationError, match="ANTHROPIC_AUTH_TOKEN is required"),
    ):
        Settings(host="0.0.0.0", voice_note_enabled=False)


def test_managed_nonempty_token_allows_non_loopback_bind() -> None:
    with patch(
        "free_claude_code.config.settings.env_file_override",
        return_value="managed-token",
    ):
        settings = Settings(host="0.0.0.0", voice_note_enabled=False)
    assert settings.anthropic_auth_token == "managed-token"
