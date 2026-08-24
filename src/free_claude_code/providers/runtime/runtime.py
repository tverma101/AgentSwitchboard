"""One closable generation of lazily constructed provider clients."""

import asyncio
from collections.abc import Callable, MutableMapping

from free_claude_code.config.settings import Settings
from free_claude_code.core.provider_policy import (
    ProviderEgressGuard,
    ProviderPolicy,
    ProviderPolicyError,
)
from free_claude_code.providers.base import BaseProvider

from .factory import create_provider

ProviderConstructor = Callable[[str, Settings], BaseProvider]


class ProviderRuntime:
    """Own provider instances for one immutable settings snapshot."""

    def __init__(
        self,
        settings: Settings,
        providers: MutableMapping[str, BaseProvider] | None = None,
        *,
        provider_constructor: ProviderConstructor = create_provider,
    ) -> None:
        self.settings = settings
        self._providers = providers if providers is not None else {}
        self._provider_constructor = provider_constructor
        self.policy = ProviderPolicy.from_settings(settings)
        self.egress_guard = (
            ProviderEgressGuard(self.policy)
            if self.policy.primary_provider == "opencode_go"
            else None
        )

    def is_cached(self, provider_id: str) -> bool:
        """Return whether a provider for this id is already cached."""
        return provider_id in self._providers

    def resolve_provider(self, provider_id: str) -> BaseProvider:
        """Return an existing provider or create it lazily."""
        return self._resolve_provider(provider_id)

    def resolve_provider_for_session(
        self,
        provider_id: str,
        *,
        model: str | None = None,
        category: str = "model",
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> BaseProvider:
        """Resolve one route with explicit session admission metadata."""
        return self._resolve_provider(
            provider_id,
            model=model,
            category=category,
            session_id=session_id,
            request_id=request_id,
        )

    def _resolve_provider(
        self,
        provider_id: str,
        *,
        model: str | None = None,
        category: str = "model",
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> BaseProvider:
        if self.egress_guard is not None and not self.egress_guard.check(
            provider_id,
            model=model,
            category=category,
            session_id=session_id,
            request_id=request_id,
        ):
            raise ProviderPolicyError(
                "provider route blocked before provider construction"
            )
        if provider_id not in self._providers:
            provider = self._provider_constructor(provider_id, self.settings)
            if self.egress_guard is not None:
                provider.bind_egress_guard(self.egress_guard)
            self._providers[provider_id] = provider
        return self._providers[provider_id]

    def resolve_helper(
        self,
        provider_id: str,
        model: str,
        *,
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> BaseProvider:
        """Resolve an explicitly allow-listed helper route."""
        return self.resolve_provider_for_session(
            provider_id,
            model=model,
            category="helper",
            session_id=session_id,
            request_id=request_id,
        )

    def egress_receipt(self, session_id: str | None = None) -> dict[str, object]:
        """Return sanitized policy and accounting metadata for this runtime."""
        if self.egress_guard is None:
            return self.policy.preview_receipt()
        return self.egress_guard.receipt(session_id)

    async def cleanup(self) -> None:
        """Release every provider client constructed by this generation."""
        errors: list[Exception] = []
        for provider_id, provider in list(self._providers.items()):
            try:
                await provider.cleanup()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                errors.append(exc)
            else:
                self._providers.pop(provider_id, None)
        if len(errors) == 1:
            raise errors[0]
        if len(errors) > 1:
            raise ExceptionGroup("One or more provider cleanups failed", errors)
