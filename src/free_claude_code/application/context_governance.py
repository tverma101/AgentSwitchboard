"""Application wiring for the provider-independent context governor."""

from pathlib import Path

from free_claude_code.config.paths import config_dir_path
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.context_governor import (
    ContextGovernanceError,
    ContextGovernanceRecord,
    ContextGovernorConfig,
    GovernedTokenCountRequest,
    govern_messages_request,
    govern_token_count_request,
)
from free_claude_code.core.anthropic.models import MessagesRequest, TokenCountRequest
from free_claude_code.core.trace import trace_event

from .media_budget import PreservedMediaBudgetError, validate_preserved_media_budget
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
    vision-capable routes while a separate aggregate media ceiling prevents
    byte-for-byte preservation from becoming an unbounded context bypass.
    """

    _validate_media_budget_if_enabled(
        request,
        settings=settings,
        preserve_media=preserve_media,
    )
    governed = govern_messages_request(
        request,
        _context_governor_config(settings, preserve_media=preserve_media),
    )
    _trace_governance_records(governed.records, request_id=request_id)
    return governed.request


def apply_context_governor_to_token_count(
    request: TokenCountRequest,
    settings: Settings,
    *,
    request_id: str,
    preserve_media: bool = True,
) -> TokenCountRequest:
    """Apply message-ingress governance before a context count probe.

    The count endpoint must estimate the same governed payload that the
    subsequent ``/messages`` request forwards, otherwise Claude Code's meter
    can jump based on raw tool output that FCC has already redirected.
    """

    _validate_media_budget_if_enabled(
        request,
        settings=settings,
        preserve_media=preserve_media,
    )
    governed: GovernedTokenCountRequest = govern_token_count_request(
        request,
        _context_governor_config(settings, preserve_media=preserve_media),
    )
    _trace_governance_records(governed.records, request_id=request_id)
    return governed.request


def _validate_media_budget_if_enabled(
    request: MessagesRequest | TokenCountRequest,
    *,
    settings: Settings,
    preserve_media: bool,
) -> None:
    if not settings.context_governor_enabled or not preserve_media:
        return
    try:
        validate_preserved_media_budget(request)
    except PreservedMediaBudgetError as exc:
        raise ContextGovernanceError(str(exc)) from exc


def _context_governor_config(
    settings: Settings,
    *,
    preserve_media: bool,
) -> ContextGovernorConfig:
    artifact_dir = (
        Path(settings.context_governor_artifact_dir).expanduser()
        if settings.context_governor_artifact_dir.strip()
        else config_dir_path() / CONTEXT_ARTIFACTS_DIRNAME
    )
    return ContextGovernorConfig(
        enabled=settings.context_governor_enabled,
        tool_result_max_bytes=settings.context_governor_tool_result_max_bytes,
        preserve_media=preserve_media,
        artifact_dir=artifact_dir,
    )


def _trace_governance_records(
    records: tuple[ContextGovernanceRecord, ...],
    *,
    request_id: str,
) -> None:
    """Emit metadata-only receipts for either governance entry point."""
    for record in records:
        trace_event(
            stage="ingress",
            event="free_claude_code.context_governor.tool_result_redirected",
            source="api",
            request_id=request_id,
            **record.as_trace_fields(),
        )


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
    "apply_context_governor_to_token_count",
    "should_preserve_media_for_model",
]
