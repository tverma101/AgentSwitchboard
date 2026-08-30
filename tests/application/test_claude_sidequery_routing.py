"""Regression guards for Claude Code small-fast/background model routing."""

from free_claude_code.application.routing import ModelRouter
from free_claude_code.cli.claude_env import build_claude_proxy_env
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    settings = Settings()
    settings.model = "opencode_go/muse-spark-1.2-contributor"
    settings.model_haiku = None
    settings.subagent_model_inherit = False
    return settings


def test_literal_haiku_falls_back_to_configured_controller() -> None:
    resolved = ModelRouter(_settings()).resolve("haiku")

    assert resolved.original_model == "haiku"
    assert resolved.provider_id == "opencode_go"
    assert resolved.provider_model == "muse-spark-1.2-contributor"
    assert resolved.provider_model_ref == "opencode_go/muse-spark-1.2-contributor"
    assert resolved.route_source == "model"


def test_canonical_haiku_id_falls_back_to_configured_controller() -> None:
    resolved = ModelRouter(_settings()).resolve("claude-haiku-4-5-20251001")

    assert resolved.original_model == "claude-haiku-4-5-20251001"
    assert resolved.provider_id == "opencode_go"
    assert resolved.provider_model == "muse-spark-1.2-contributor"
    assert resolved.provider_model_ref == "opencode_go/muse-spark-1.2-contributor"
    assert resolved.route_source == "model"


def test_explicit_haiku_route_still_wins_when_configured() -> None:
    settings = _settings()
    settings.model_haiku = "lmstudio/qwen2.5-7b"

    resolved = ModelRouter(settings).resolve("haiku")

    assert resolved.provider_id == "lmstudio"
    assert resolved.provider_model == "qwen2.5-7b"
    assert resolved.provider_model_ref == "lmstudio/qwen2.5-7b"
    assert resolved.route_source == "model_haiku"


def test_claude_proxy_env_does_not_inherit_external_haiku_routes() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-5-20251001",
            "ANTHROPIC_SMALL_FAST_MODEL": "legacy-haiku-route",
        },
        model_id="opencode_go/muse-spark-1.2-contributor",
        process_wrapper_path="/private/tmp/fcc-wrapper",
    )

    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL" not in env
    assert "ANTHROPIC_SMALL_FAST_MODEL" not in env
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8082"
    assert env["CLAUDE_CODE_PROCESS_WRAPPER"] == "/private/tmp/fcc-wrapper"
