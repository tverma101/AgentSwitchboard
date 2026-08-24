from free_claude_code.application.route_diagnostics import build_route_diagnostic
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


def test_diagnostic_exposes_default_child_route_source_without_network() -> None:
    payload = build_route_diagnostic(
        _settings(),
        model="claude-3-haiku-20240307",
    )

    assert payload["network"] == "none"
    assert payload["billable_requests"] == 0
    assert payload["controller"]["provider"] == "opencode_go"
    assert payload["controller"]["model"] == "muse-spark-1.2-contributor"
    assert payload["controller"]["route_source"] == "model"
    assert payload["controller"]["alias_applied"] is False


def test_diagnostic_exposes_stale_haiku_override_source_without_network() -> None:
    settings = _settings()
    settings.model_haiku = "opencode_zen/kimi-k2.6"

    payload = build_route_diagnostic(
        settings,
        model="claude-3-haiku-20240307",
    )

    assert payload["network"] == "none"
    assert payload["billable_requests"] == 0
    assert payload["controller"]["provider"] == "opencode_zen"
    assert payload["controller"]["model"] == "kimi-k2.6"
    assert payload["controller"]["route_source"] == "model_haiku"
    assert payload["controller"]["alias_applied"] is False
