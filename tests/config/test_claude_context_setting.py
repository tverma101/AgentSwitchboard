import pytest
from pydantic import ValidationError

from free_claude_code.cli.claude_env import build_claude_proxy_env
from free_claude_code.config.admin.manifest import FIELD_BY_KEY
from free_claude_code.config.settings import Settings


def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.delenv("FCC_CLAUDE_CONTEXT_TOKENS", raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    return Settings()


def test_claude_context_window_defaults_to_256k(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _isolated_settings(monkeypatch)

    assert settings.claude_context_tokens == 256_000


def test_claude_context_window_accepts_272k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FCC_CLAUDE_CONTEXT_TOKENS", "272000")
    monkeypatch.setitem(Settings.model_config, "env_file", ())

    settings = Settings()

    assert settings.claude_context_tokens == 272_000


def test_claude_context_window_rejects_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FCC_CLAUDE_CONTEXT_TOKENS", "1000001")
    monkeypatch.setitem(Settings.model_config, "env_file", ())

    with pytest.raises(ValidationError, match="FCC_CLAUDE_CONTEXT_TOKENS"):
        Settings()


def test_admin_manifest_exposes_claude_context_window() -> None:
    field = FIELD_BY_KEY["FCC_CLAUDE_CONTEXT_TOKENS"]

    assert field.settings_attr == "claude_context_tokens"
    assert field.field_type == "number"
    assert field.default == "256000"


def test_claude_proxy_env_honors_272k_window() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={"FCC_CLAUDE_CONTEXT_TOKENS": "272000"},
    )

    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "272000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "272000"
