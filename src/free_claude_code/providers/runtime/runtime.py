"""One closable generation of lazily constructed provider clients."""

import asyncio
from collections.abc import Callable, MutableMapping

from free_claude_code.application.session_policy import SessionExecutionPolicy
from free_claude_code.config.settings import Settings
from free_claude_code.providers.base import BaseProvider

from .factory import create_provider

ProviderConstructor = Callable[[str, Settings], BaseProvider]
_CLEANUP_PASSES = 2


class ProviderRuntime:
    """Own provider instances for one immutable settings snapshot."""

    def __init__(
        self,
        settings: Settings,
        providers: MutableMapping[str, BaseProvider] | None = None,
        *,
        provider_constructor: ProviderConstructor = create_provider,
        session_policy: SessionExecutionPolicy | None = None,
    ) -> None:
        self.settings = settings
        self._providers = providers if providers is not None else {}
        self._provider_constructor = provider_constructor
        self.session_policy = session_policy

    def is_cached(self, provider_id: str) -> bool:
        """Return whether a provider for this id is already cached."""
        return provider_id in self._providers

    def resolve_provider(self, provider_id: str) -> BaseProvider:
        """Return an existing provider or create it lazily."""
        if provider_id not in self._providers:
            self._providers[provider_id] = self._provider_constructor(
                provider_id, self.settings
            )
        return self._providers[provider_id]

    async def cleanup(self) -> None:
        """Release every provider client, retrying only transient failures once."""
        errors: list[Exception] = []
        for cleanup_pass in range(_CLEANUP_PASSES):
            errors = []
            for provider_id, provider in list(self._providers.items()):
                try:
                    await provider.cleanup()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    errors.append(exc)
                else:
                    self._providers.pop(provider_id, None)
            if not errors:
                return
            if cleanup_pass + 1 < _CLEANUP_PASSES:
                # Give close callbacks scheduled by the failed attempt one event-loop
                # turn to settle before retrying the providers that remain cached.
                await asyncio.sleep(0)
        if len(errors) == 1:
            raise errors[0]
        raise ExceptionGroup("One or more provider cleanups failed", errors)
