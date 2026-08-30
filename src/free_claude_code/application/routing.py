"""Model routing for Claude-compatible requests."""

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from threading import RLock

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
class _ParentRouteEntry:
    """One generation-scoped parent route stored for a Claude session."""

    generation_id: int | None
    resolved: ResolvedModel


class ParentRouteRegistry:
    """Keep a bounded, private parent route snapshot for each Claude session.

    Claude Code can use different logical model names for work performed by a
    subagent.  The proxy therefore needs a small amount of session state to
    retain the route selected for the parent request.  Only a SHA-256 digest of
    the opaque session id is stored, and entries are invalidated when the
    provider generation changes so a config reload cannot reuse an old route.
    """

    def __init__(self, *, max_entries: int = 256) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._entries: OrderedDict[str, _ParentRouteEntry] = OrderedDict()
        self._max_entries = max_entries
        self._lock = RLock()

    def lookup(
        self,
        session_id: str | None,
        *,
        generation_id: int | None = None,
    ) -> ResolvedModel | None:
        """Return the session route when it belongs to this provider generation."""

        key = _session_key(session_id)
        if key is None:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if (
                generation_id is not None
                and entry.generation_id is not None
                and entry.generation_id != generation_id
            ):
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return entry.resolved

    def remember(
        self,
        session_id: str | None,
        resolved: ResolvedModel,
        *,
        generation_id: int | None = None,
    ) -> None:
        """Store the first route for a session, replacing it only on restart.

        Retaining the first route is deliberate: a child may send a direct
        provider/model request of its own, but that must not change the route
        inherited by its siblings or by later turns of the parent session.
        """

        key = _session_key(session_id)
        if key is None:
            return
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None and (
                generation_id is None or existing.generation_id == generation_id
            ):
                self._entries.move_to_end(key)
                return
            self._entries[key] = _ParentRouteEntry(
                generation_id=generation_id,
                resolved=resolved,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        """Discard all retained session routes."""

        with self._lock:
            self._entries.clear()


def _session_key(session_id: str | None) -> str | None:
    """Hash one bounded opaque session id without retaining user identifiers."""

    if not isinstance(session_id, str):
        return None
    normalized = session_id.strip()
    if not normalized or len(normalized) > 512:
        return None
    return sha256(normalized.encode("utf-8")).hexdigest()


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

    def resolve(
        self,
        claude_model_name: str,
        *,
        parent_route: ResolvedModel | None = None,
    ) -> ResolvedModel:
        """Resolve a model, inheriting the parent route for logical children."""

        normalized_inbound = normalize_model_ref(claude_model_name)
        alias_target = self._model_aliases.resolve_if_configured(
            normalized_inbound.model_ref
        )
        alias_applied = alias_target != normalized_inbound.model_ref
        normalized_target = normalize_model_ref(alias_target)
        requested_model = normalized_target.model_ref
        virtual_context_window = (
            normalized_inbound.virtual_context_window
            if normalized_inbound.virtual_context_window is not None
            else normalized_target.virtual_context_window
        )
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

        if (
            parent_route is not None
            and self._subagent_model_inheritance_enabled()
            and not alias_applied
        ):
            logger.debug(
                "MODEL INHERIT: '{}' -> provider='{}' model='{}' source=parent_inherited",
                claude_model_name,
                parent_route.provider_id,
                parent_route.provider_model,
            )
            return self._resolve_from_parent(
                claude_model_name,
                parent_route,
                virtual_context_window=virtual_context_window,
            )

        configured_ref, route_source = self._resolve_model_ref_with_source(
            requested_model
        )
        configured_model = normalize_model_ref(configured_ref)
        provider_model_ref = configured_model.model_ref
        if virtual_context_window is None:
            virtual_context_window = configured_model.virtual_context_window
        reasoning_preference = self._resolve_reasoning_preference(
            claude_model_name,
            use_route_override=(
                alias_applied or not self._subagent_model_inheritance_enabled()
            ),
        )
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

    def _resolve_from_parent(
        self,
        claude_model_name: str,
        parent_route: ResolvedModel,
        *,
        virtual_context_window: int | None,
    ) -> ResolvedModel:
        """Project the parent provider route onto the child's model name."""

        if virtual_context_window is None:
            virtual_context_window = parent_route.virtual_context_window
        return ResolvedModel(
            original_model=claude_model_name,
            provider_id=parent_route.provider_id,
            provider_model=parent_route.provider_model,
            provider_model_ref=parent_route.provider_model_ref,
            reasoning_preference=parent_route.reasoning_preference,
            virtual_context_window=virtual_context_window,
            route_source="parent_inherited",
            alias_applied=False,
        )

    def _subagent_model_inheritance_enabled(self) -> bool:
        """Return the safe default for parent-model inheritance."""

        return bool(getattr(self._settings, "subagent_model_inherit", True))

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
        self,
        claude_model_name: str,
        *,
        use_route_override: bool,
    ) -> ReasoningPreference:
        """Resolve a route override without inspecting the provider model."""

        route = self._matched_route(claude_model_name)
        if use_route_override and route is not None:
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
        self,
        request: MessagesRequest,
        *,
        parent_route: ResolvedModel | None = None,
    ) -> RoutedMessagesRequest:
        """Return an internal routed request context."""
        resolved = self.resolve(request.model, parent_route=parent_route)
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
        self,
        request: TokenCountRequest,
        *,
        parent_route: ResolvedModel | None = None,
    ) -> RoutedTokenCountRequest:
        """Return an internal token-count request context."""
        resolved = self.resolve(request.model, parent_route=parent_route)
        routed = request.model_copy(
            update={"model": resolved.provider_model}, deep=True
        )
        return RoutedTokenCountRequest(request=routed, resolved=resolved)
