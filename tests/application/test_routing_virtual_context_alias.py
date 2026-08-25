from free_claude_code.application.routing import ModelRouter
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.models import Message, MessagesRequest


# Regression provenance: https://github.com/musistudio/claude-code-router/issues/1697
def test_model_alias_survives_client_virtual_context_suffix() -> None:
    settings = Settings()
    settings.model = "nvidia_nim/fallback-model"
    settings.model_aliases = "muse=opencode_go/minimax-m2.7[1m]"
    request = MessagesRequest(
        model="muse[200k]",
        max_tokens=100,
        messages=[Message(role="user", content="hello")],
    )

    routed = ModelRouter(settings).resolve_messages_request(request)

    assert routed.request.model == "minimax-m2.7"
    assert routed.resolved.provider_id == "opencode_go"
    assert routed.resolved.provider_model_ref == "opencode_go/minimax-m2.7"
    assert routed.resolved.virtual_context_window == 200_000
    assert routed.resolved.alias_applied is True
    assert request.model == "muse[200k]"
