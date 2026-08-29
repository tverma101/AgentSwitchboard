"""Application wiring for the provider-independent context governor."""

from pathlib import Path

from free_claude_code.config.paths import config_dir_path
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.context_governor import (
    ContextGovernanceError,
    ContextGovernorConfig,
    GovernedMessagesRequest,
    govern_messages_request,
)
from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.trace import trace_event

from .model_metadata import ProviderModelInfo

CONTEXT_ARTIFACTS_DIRNAME = "context-artifacts"


def apply_context_governor(
    request: MessagesRequest,
    settings: Settings,
    *,
    request_id: str,
    preserve_media: bool = True,
) -> MessagesRequest:
    """Apply the configured governor and emit metadata-only evidence.

    ``preserve_media`` is selected by the routed application path after model
    capability validation. It keeps complete image/document blocks intact for
    vision-capable routes; the core governor remains unaware of provider/model
    metadata.
    """

    artifact_dir = (
        Path(settings.context_governor_artifact_dir).expanduser()
        if settings.context_governor_artifact_dir.strip()
        else config_dir_path() / CONTEXT_ARTIFACTS_DIRNAME
    )
    governed: GovernedMessagesRequest = govern_messages_request(
        request,
        ContextGovernorConfig(
            enabled=settings.context_governor_enabled,
            tool_result_max_bytes=settings.context_governor_tool_result_max_bytes,
            preserve_media=preserve_media,
            artifact_dir=artifact_dir,
        ),
    )
    for record in governed.records:
        trace_event(
            stage="ingress",
            event="free_claude_code.context_governor.tool_result_redirected",
            source="api",
            request_id=request_id,
            **record.as_trace_fields(),
        )
    return governed.request


def should_preserve_media_for_model(
    settings: Settings,
    model_info: ProviderModelInfo | None,
) -> bool:
    """Return whether the selected route should keep complete media blocks.

    Explicit non-vision metadata is rejected by visual capability validation
    before this decision. Unknown metadata is preserved rather than silently
    destroying an image; the provider protocol remains responsible for the
    final compatibility decision.
    """

    return settings.context_governor_preserve_media and (
        model_info is None or model_info.effective_supports_vision() is not False
    )


__all__ = [
    "ContextGovernanceError",
    "apply_context_governor",
    "should_preserve_media_for_model",
]
