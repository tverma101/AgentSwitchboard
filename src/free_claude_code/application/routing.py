"""Model routing for Claude-compatible requests."""

from dataclasses import dataclass

from loguru import logger

from free_claude_code.application.errors import UnknownProviderError
from free_claude_code.config.model_aliases import parse_model_aliases
from free_claude_code.config.model_refs import (
    normalize_model_ref,
    parse_model_name,
    parse_provider_type,
)
from free_claude_code.config.provider_catalog import (
    PROVIDER_CATALOG,
    SUPPORTED_PROVIDER_IDS,
)
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic import MessagesRequest, TokenCountRequest
from free_claude_code.core.gateway_model_ids import decode_gateway_model_id
from free_claude_code.core.reasoning import ReasoningPolicy

from .reasoning import resolve_reasoning_policy

_ROUTE_SETTINGS = (
    ("fable", "model_fable", "reasoning_fable"),
    ("opus", "model_opus", "reasoning_opus"),
    ("haiku", "model_haiku", "reasoning_haiku"),
    ("sonnet", "model_sonnet", "reasoning_sonnet"),
)


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    original_model: str
    provider_id: str
    provider_model: str
    provider_model_ref: str
    reasoning_preference: ReasoningPreference
    virtual_context_window: int | None = None
    route_source: str = "unknown"
    alias_applied: bool = False


@dataclass(frozen=True, slots=True)
class RoutedMessagesRequest:
    request: MessagesRequest
    resolved: ResolvedModel
    reasoning: ReasoningPolicy


@dataclass(frozen=True, slots=True)
class RoutedTokenCountRequest:
    request: TokenCountRequest
    resolved: ResolvedModel


class ModelRouter:
    """Resolve incoming Claude model names to configured provider/model pairs."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model_aliases = parse_model_aliases(
            getattr(settings, "model_aliases", "")
        )

    def resolve(self, claude_model_name: str) -> ResolvedModel:
        alias_target = self._model_aliases.resolve_if_configured(claude_model_name)
        alias_applied = alias_target != claude_model_name
        normalized_requested = normalize_model_ref(alias_target)
        requested_model = normalized_requested.model_ref
        virtual_context_window = normalized_requested.virtual_context_window
        (
            direct_provider_id,
            direct_provider_model,
            force_reasoning_off,
        ) = self._direct_provider_model(requested_model)
        if direct_provider_id is not None and direct_provider_model is not None:
            reasoning_preference = (
                ReasoningPreference.OFF
                if force_reasoning_off
                else self._settings.reasoning_policy
            )
            route_source = "model_alias" if alias_applied else "request_model"
            logger.debug(
                "MODEL DIRECT: '{}' -> provider='{}' model='{}' reasoning={} source={}",
                claude_model_name,
                direct_provider_id,
                direct_provider_model,
                reasoning_preference.value,
                route_source,
            )
            return ResolvedModel(
                original_model=claude_model_name,
                provider_id=direct_provider_id,
                provider_model=direct_provider_model,
                provider_model_ref=requested_model,
                reasoning_preference=reasoning_preference,
                virtual_context_window=virtual_context_window,
                route_source=route_source,
                alias_applied=alias_applied,
            )

        configured_ref, route_source = self._resolve_model_ref_with_source(
            requested_model
        )
        configured_model = normalize_model_ref(configured_ref)
        provider_model_ref = configured_model.model_ref
        if virtual_context_window is None:
            virtual_context_window = configured_model.virtual_context_window
        reasoning_preference = self._resolve_reasoning_preference(claude_model_name)
        provider_id = parse_provider_type(provider_model_ref)
        self._validate_provider_id(provider_id)
        provider_model = parse_model_name(provider_model_ref)
        if provider_model != claude_model_name:
            logger.debug(
                "MODEL MAPPING: '{}' -> '{}' source={}",
                claude_model_name,
                provider_model,
                route_source,
            )
        return ResolvedModel(
            original_model=claude_model_name,
            provider_id=provider_id,
            provider_model=provider_model,
            provider_model_ref=provider_model_ref,
            reasoning_preference=reasoning_preference,
            virtual_context_window=virtual_context_window,
            route_source=route_source,
            alias_applied=alias_applied,
        )

    @staticmethod
    def _validate_provider_id(provider_id: str) -> None:
        if provider_id not in PROVIDER_CATALOG:
            raise UnknownProviderError.for_provider(provider_id, PROVIDER_CATALOG)

    def _direct_provider_model(
        self, model_name: str
    ) -> tuple[str | None, str | None, bool]:
        decoded = decode_gateway_model_id(model_name)
        if decoded is not None:
            if decoded.provider_id not in SUPPORTED_PROVIDER_IDS:
                return None, None, False
            return (
                decoded.provider_id,
                decoded.provider_model,
                decoded.force_reasoning_off,
            )

        provider_id, separator, provider_model = model_name.partition("/")
        if not separator:
            return None, None, False
        if provider_id not in SUPPORTED_PROVIDER_IDS:
            return None, None, False
        if not provider_model:
            return None, None, False
        return provider_id, provider_model, False

    def _resolve_model_ref(self, claude_model_name: str) -> str:
        """Resolve a Claude model name to the configured provider/model ref."""

        model_ref, _source = self._resolve_model_ref_with_source(claude_model_name)
        return model_ref

    def _resolve_model_ref_with_source(self, claude_model_name: str) -> tuple[str, str]:
        """Resolve the model ref and retain the exact setting that selected it."""

        route = self._matched_route(claude_model_name)
        if route is not None:
            model = getattr(self._settings, route[1])
            if isinstance(model, str):
                return model, route[1]
        return self._settings.model, "model"

    def _resolve_reasoning_preference(
        self, claude_model_name: str
    ) -> ReasoningPreference:
        """Resolve a route override without inspecting the provider model."""

        route = self._matched_route(claude_model_name)
        if route is not None:
            preference = getattr(self._settings, route[2])
            if preference is not ReasoningPreference.INHERIT:
                return preference
        return self._settings.reasoning_policy

    @staticmethod
    def _matched_route(model_name: str) -> tuple[str, str, str] | None:
        normalized = model_name.lower()
        return next(
            (route for route in _ROUTE_SETTINGS if route[0] in normalized),
            None,
        )

    def resolve_messages_request(
        self, request: MessagesRequest
    ) -> RoutedMessagesRequest:
        """Return an internal routed request context."""
        resolved = self.resolve(request.model)
        routed = request.model_copy(deep=True)
        routed.model = resolved.provider_model
        return RoutedMessagesRequest(
            request=routed,
            resolved=resolved,
            reasoning=resolve_reasoning_policy(
                routed,
                resolved.reasoning_preference,
            ),
        )

    def resolve_token_count_request(
        self, request: TokenCountRequest
    ) -> RoutedTokenCountRequest:
        """Return an internal token-count request context."""
        resolved = self.resolve(request.model)
        routed = request.model_copy(
            update={"model": resolved.provider_model}, deep=True
        )
        return RoutedTokenCountRequest(request=routed, resolved=resolved)
