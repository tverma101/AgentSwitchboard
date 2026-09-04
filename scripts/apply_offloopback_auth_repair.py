from pathlib import Path


SETTINGS = Path("src/free_claude_code/config/settings.py")
TEST = Path("tests/config/test_server_binding_auth.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


text = SETTINGS.read_text()
if "import ipaddress\n" not in text:
    text = replace_once(
        text,
        '"""Flat application settings schema loaded by Pydantic Settings."""\n\n',
        '"""Flat application settings schema loaded by Pydantic Settings."""\n\nimport ipaddress\n',
        "ipaddress import",
    )

text = replace_once(
    text,
    """    # Optional proxy bearer token protecting public API endpoints.\n    # Set via env `ANTHROPIC_AUTH_TOKEN`. When empty, no auth is required.\n""",
    """    # Optional proxy bearer token protecting public API endpoints.\n    # Set via env `ANTHROPIC_AUTH_TOKEN`. Empty is allowed only on loopback.\n""",
    "auth comment",
)

anchor = """    @model_validator(mode=\"after\")\n    def prefer_dotenv_anthropic_auth_token(self) -> Settings:\n        \"\"\"Let explicit .env auth config override stale shell/client tokens.\"\"\"\n        dotenv_value = env_file_override(self.model_config, ANTHROPIC_AUTH_TOKEN_ENV)\n        if dotenv_value is not None:\n            self.anthropic_auth_token = dotenv_value\n        return self\n\n"""
validator = """    @model_validator(mode=\"after\")\n    def require_auth_for_non_loopback_host(self) -> Settings:\n        \"\"\"Prevent an unauthenticated proxy from binding beyond this machine.\"\"\"\n        normalized_host = self.host.strip().strip(\"[]\").casefold()\n        is_loopback = normalized_host == \"localhost\"\n        if not is_loopback:\n            try:\n                is_loopback = ipaddress.ip_address(normalized_host).is_loopback\n            except ValueError:\n                is_loopback = False\n        if not is_loopback and not self.anthropic_auth_token.strip():\n            raise ValueError(\n                \"ANTHROPIC_AUTH_TOKEN is required when HOST is not loopback; \"\n                \"use HOST=127.0.0.1 for an unauthenticated local server\"\n            )\n        return self\n\n"""
if "def require_auth_for_non_loopback_host" not in text:
    text = replace_once(text, anchor, anchor + validator, "auth validator")
SETTINGS.write_text(text)

TEST.write_text(
    '''from unittest.mock import patch\n\nimport pytest\nfrom pydantic import ValidationError\n\nfrom free_claude_code.config.settings import Settings\n\n\n@pytest.fixture(autouse=True)\ndef clear_server_auth_env(monkeypatch) -> None:\n    monkeypatch.setitem(Settings.model_config, "env_file", ())\n    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)\n    monkeypatch.delenv("HOST", raising=False)\n\n\n@pytest.mark.parametrize(\n    "host", ["127.0.0.1", "127.0.0.42", "::1", "[::1]", "localhost"]\n)\ndef test_loopback_server_may_run_without_proxy_token(host: str) -> None:\n    with patch(\n        "free_claude_code.config.settings.env_file_override",\n        return_value=None,\n    ):\n        settings = Settings(host=host, voice_note_enabled=False)\n    assert settings.host == host\n    assert settings.anthropic_auth_token == ""\n\n\n@pytest.mark.parametrize(\n    "host", ["0.0.0.0", "::", "192.168.1.10", "proxy.example.test"]\n)\ndef test_non_loopback_server_requires_proxy_token(host: str) -> None:\n    with (\n        patch(\n            "free_claude_code.config.settings.env_file_override",\n            return_value=None,\n        ),\n        pytest.raises(ValidationError, match="ANTHROPIC_AUTH_TOKEN is required"),\n    ):\n        Settings(host=host, voice_note_enabled=False)\n\n\ndef test_non_loopback_server_accepts_environment_proxy_token(monkeypatch) -> None:\n    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")\n    with patch(\n        "free_claude_code.config.settings.env_file_override",\n        return_value=None,\n    ):\n        settings = Settings(host="0.0.0.0", voice_note_enabled=False)\n    assert settings.host == "0.0.0.0"\n    assert settings.anthropic_auth_token == "test-token"\n\n\ndef test_managed_empty_token_rejects_non_loopback_bind(monkeypatch) -> None:\n    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "process-token")\n    with (\n        patch(\n            "free_claude_code.config.settings.env_file_override",\n            return_value="",\n        ),\n        pytest.raises(ValidationError, match="ANTHROPIC_AUTH_TOKEN is required"),\n    ):\n        Settings(host="0.0.0.0", voice_note_enabled=False)\n\n\ndef test_managed_nonempty_token_allows_non_loopback_bind() -> None:\n    with patch(\n        "free_claude_code.config.settings.env_file_override",\n        return_value="managed-token",\n    ):\n        settings = Settings(host="0.0.0.0", voice_note_enabled=False)\n    assert settings.anthropic_auth_token == "managed-token"\n'''
)
