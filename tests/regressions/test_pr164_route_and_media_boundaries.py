import pytest

from free_claude_code.api.handlers.messages import MessagesHandler
from free_claude_code.api.handlers.token_count import TokenCountHandler
from free_claude_code.application.context_governance import (
    ContextGovernanceError,
    apply_context_governor,
    apply_context_governor_to_token_count,
)
from free_claude_code.application.errors import InvalidRequestError
from free_claude_code.application.ports import ProviderPort
from free_claude_code.application.routing import ParentRouteRegistry
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.models import MessagesRequest, TokenCountRequest


def _settings() -> Settings:
    return Settings().model_copy(
        update={
            "model": "openai/gpt-test",
            "model_haiku": "openai/gpt-test",
        }
    )


def _unreachable_provider_resolver(_provider_id: str) -> ProviderPort:
    raise AssertionError("provider resolution should not run")


def test_count_tokens_never_establishes_parent_route() -> None:
    registry = ParentRouteRegistry()
    handler = TokenCountHandler(
        _settings(),
        generation_id=7,
        parent_route_registry=registry,
    )
    request = TokenCountRequest(
        model="claude-haiku-4",
        claude_session_id="session-before-parent",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert handler.count(request).input_tokens > 0
    assert registry.lookup("session-before-parent", generation_id=7) is None


@pytest.mark.asyncio
async def test_rejected_message_does_not_establish_parent_route() -> None:
    registry = ParentRouteRegistry()
    settings = _settings().model_copy(
        update={"context_governor_tool_result_max_bytes": 1024}
    )
    handler = MessagesHandler(
        settings,
        _unreachable_provider_resolver,
        generation_id=7,
        parent_route_registry=registry,
    )
    request = MessagesRequest(
        model="claude-haiku-4",
        claude_session_id="rejected-parent",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-large-structured",
                        "content": {"blob": "x" * 4096},
                    }
                ],
            }
        ],
    )

    with pytest.raises(InvalidRequestError):
        await handler.create(request)

    assert registry.lookup("rejected-parent", generation_id=7) is None


def test_preserved_media_has_same_hard_budget_for_messages_and_count_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from free_claude_code.application import media_budget

    monkeypatch.setattr(media_budget, "MAX_PRESERVED_MEDIA_BYTES", 128)
    settings = _settings()
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "x" * 256,
            },
        }
    ]
    messages = [{"role": "user", "content": content}]

    with pytest.raises(ContextGovernanceError, match="preserved media exceeds"):
        apply_context_governor(
            MessagesRequest(model="claude-haiku-4", messages=messages),
            settings,
            request_id="messages-budget",
            preserve_media=True,
        )

    with pytest.raises(ContextGovernanceError, match="preserved media exceeds"):
        apply_context_governor_to_token_count(
            TokenCountRequest(model="claude-haiku-4", messages=messages),
            settings,
            request_id="count-budget",
            preserve_media=True,
        )
