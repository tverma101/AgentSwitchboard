from free_claude_code.application.routing import ModelRouter
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    settings = Settings()
    settings.model = "opencode_go/muse-spark-1.2-contributor"
    settings.model_fable = None
    settings.model_opus = None
    settings.model_sonnet = None
    settings.model_haiku = None
    settings.model_aliases = ""
    settings.reasoning_policy = ReasoningPreference.CLIENT
    settings.reasoning_fable = ReasoningPreference.INHERIT
    settings.reasoning_opus = ReasoningPreference.INHERIT
    settings.reasoning_sonnet = ReasoningPreference.INHERIT
    settings.reasoning_haiku = ReasoningPreference.INHERIT
    return settings


def test_haiku_child_without_override_inherits_default_muse_route() -> None:
    resolved = ModelRouter(_settings()).resolve("claude-3-haiku-20240307")

    assert resolved.provider_id == "opencode_go"
    assert resolved.provider_model == "muse-spark-1.2-contributor"
    assert resolved.provider_model_ref == "opencode_go/muse-spark-1.2-contributor"
    assert resolved.route_source == "model"
    assert resolved.alias_applied is False


def test_stale_haiku_override_to_zen_is_explicitly_attributed() -> None:
    settings = _settings()
    settings.model_haiku = "opencode_zen/kimi-k2.6"

    resolved = ModelRouter(settings).resolve("claude-3-haiku-20240307")

    assert resolved.provider_id == "opencode_zen"
    assert resolved.provider_model == "kimi-k2.6"
    assert resolved.provider_model_ref == "opencode_zen/kimi-k2.6"
    assert resolved.route_source == "model_haiku"
    assert resolved.alias_applied is False


def test_direct_provider_route_records_request_model_source() -> None:
    resolved = ModelRouter(_settings()).resolve("opencode_go/muse-spark-1.2-contributor")

    assert resolved.provider_id == "opencode_go"
    assert resolved.route_source == "request_model"
    assert resolved.alias_applied is False


def test_alias_route_records_alias_provenance() -> None:
    settings = _settings()
    settings.model_aliases = "muse=opencode_go/muse-spark-1.2-contributor"

    resolved = ModelRouter(settings).resolve("muse")

    assert resolved.provider_id == "opencode_go"
    assert resolved.route_source == "model_alias"
    assert resolved.alias_applied is True
