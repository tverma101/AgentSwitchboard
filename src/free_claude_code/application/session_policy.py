"""Launch-time composition for controller, helper, and provider egress policy."""

from collections.abc import Iterable
from dataclasses import dataclass

from free_claude_code.application.capabilities import (
    CapabilityRoutingMode,
    CapabilityRoutingPolicy,
)
from free_claude_code.application.helpers import (
    ApprovedHelperExecutor,
    ApprovedHelperRegistry,
)
from free_claude_code.config.custom_providers import (
    ProviderRegistry,
    provider_registry_for_settings,
)
from free_claude_code.config.model_refs import parse_model_name, parse_provider_type
from free_claude_code.config.provider_catalog import ProviderDescriptor
from free_claude_code.config.settings import Settings
from free_claude_code.core.provider_policy import (
    ProviderEgressGuard,
    ProviderPolicy,
    ProviderPolicyMode,
)

_DEFAULT_LOCAL_TOOL_FAMILIES = frozenset({"computer", "browser"})
_DEFAULT_FORBIDDEN_PROVIDER_FAMILIES = frozenset(
    {"anthropic", "openai", "codex", "chatgpt"}
)


@dataclass(frozen=True, slots=True)
class SessionExecutionPolicy:
    """One immutable policy shared by controller providers and approved helpers."""

    provider_policy: ProviderPolicy
    routing_policy: CapabilityRoutingPolicy
    allowed_helper_ids: frozenset[str]
    egress_guard: ProviderEgressGuard

    def helper_executor(
        self,
        registry: ApprovedHelperRegistry,
    ) -> ApprovedHelperExecutor:
        """Build the helper executor with the exact same egress guard instance."""

        _validate_allowed_helpers(registry, self.allowed_helper_ids)
        return ApprovedHelperExecutor(registry, self.egress_guard)

    def receipt(self) -> dict[str, object]:
        """Return metadata-only session policy and current egress counters."""

        return {
            "controller_provider": self.provider_policy.primary_provider,
            "controller_model": self.provider_policy.primary_model,
            "provider_policy_mode": self.provider_policy.mode.value,
            "capability_routing_mode": self.routing_policy.mode.value,
            "allowed_helpers": sorted(self.allowed_helper_ids),
            "allowed_provider_families": sorted(
                self.provider_policy.allowed_provider_families
            ),
            "paid_fallback": self.provider_policy.paid_fallback,
            "egress": self.egress_guard.receipt(),
        }


def build_session_execution_policy(
    controller_model_ref: str,
    registry: ApprovedHelperRegistry,
    *,
    allowed_helper_ids: Iterable[str] = (),
    allowed_provider_families: Iterable[str] = (),
    provider_mode: ProviderPolicyMode = ProviderPolicyMode.STRICT,
    routing_mode: CapabilityRoutingMode = CapabilityRoutingMode.STRICT,
    paid_fallback: bool = False,
) -> SessionExecutionPolicy:
    """Resolve one explicit immutable policy without credential/binary discovery."""

    controller_provider = parse_provider_type(controller_model_ref)
    controller_model = parse_model_name(controller_model_ref)
    allowed_ids = frozenset(
        helper_id.strip() for helper_id in allowed_helper_ids if helper_id.strip()
    )
    allowed_provider_ids = frozenset(
        provider_id.strip().lower()
        for provider_id in allowed_provider_families
        if provider_id.strip()
    )
    _validate_allowed_helpers(registry, allowed_ids)

    local_tool_families = set(_DEFAULT_LOCAL_TOOL_FAMILIES)
    remote_provider_families: set[str] = set()
    for helper_id in sorted(allowed_ids):
        helper = registry.resolve(helper_id)
        family = helper.provider_family.strip().lower()
        if helper.local:
            local_tool_families.add(family)
            continue
        if helper.billable and not paid_fallback:
            raise ValueError(
                f"billable helper requires explicit paid_fallback: {helper_id}"
            )
        remote_provider_families.add(family)

    if (
        remote_provider_families
        and provider_mode is not ProviderPolicyMode.ALLOW_LISTED
    ):
        raise ValueError("remote helpers require provider policy mode allow-listed")

    forbidden_families = set(_DEFAULT_FORBIDDEN_PROVIDER_FAMILIES)
    if paid_fallback and provider_mode is ProviderPolicyMode.ALLOW_LISTED:
        forbidden_families -= remote_provider_families

    provider_policy = ProviderPolicy(
        primary_provider=controller_provider,
        primary_model=controller_model,
        allowed_helpers=frozenset(remote_provider_families),
        allowed_provider_families=allowed_provider_ids,
        allowed_local_tools=frozenset(local_tool_families),
        forbidden_provider_families=frozenset(forbidden_families),
        mode=provider_mode,
        paid_fallback=paid_fallback,
    )
    routing_policy = CapabilityRoutingPolicy(
        mode=routing_mode,
        allowed_helpers=allowed_ids,
    )
    guard = ProviderEgressGuard(provider_policy)
    return SessionExecutionPolicy(
        provider_policy=provider_policy,
        routing_policy=routing_policy,
        allowed_helper_ids=allowed_ids,
        egress_guard=guard,
    )


def parse_allowed_helper_ids(value: str) -> tuple[str, ...]:
    """Parse the Admin/env helper allowlist without discovering helpers."""

    return tuple(
        dict.fromkeys(
            helper_id.strip()
            for part in value.replace(",", "\n").splitlines()
            for helper_id in (part,)
            if helper_id.strip()
        )
    )


def build_session_execution_policy_for_settings(
    settings: Settings,
    registry: ApprovedHelperRegistry,
) -> SessionExecutionPolicy:
    """Build the launch policy from one immutable Settings snapshot."""

    provider_registry = provider_registry_for_settings(settings)
    return build_session_execution_policy(
        settings.model,
        registry,
        allowed_helper_ids=parse_allowed_helper_ids(settings.allowed_helper_ids),
        allowed_provider_families=_configured_provider_families(
            settings, provider_registry
        ),
        provider_mode=ProviderPolicyMode(settings.provider_policy_mode),
        routing_mode=CapabilityRoutingMode(settings.capability_routing_mode),
        paid_fallback=settings.paid_fallback,
    )


def _configured_provider_families(
    settings: Settings,
    provider_registry: ProviderRegistry,
) -> frozenset[str]:
    """Return configured provider lanes eligible for model discovery/requests.

    Discovery uses the same provider runtime and pre-network egress guard as
    normal requests.  The guard therefore needs to know about every configured
    remote lane, not only the primary route and custom providers.  Disabled
    custom providers are absent from ``provider_registry``; built-ins are
    included only when their required settings are present.  Local built-ins
    remain opt-in through an explicit primary or model route and are not
    treated as remote network lanes here.
    """

    return frozenset(
        provider_id
        for provider_id, descriptor in provider_registry.catalog.items()
        if (not descriptor.local and _has_provider_configuration(descriptor, settings))
    )


def _has_provider_configuration(
    descriptor: ProviderDescriptor, settings: Settings
) -> bool:
    """Mirror the provider-runtime configuration check without importing it.

    Importing ``providers.runtime.config`` from this module would execute the
    runtime package initializer and create a session-policy import cycle.
    Keeping this small predicate local also makes policy composition independent
    from provider runtime construction.
    """

    configuration_attrs = descriptor.configuration_attrs()
    if configuration_attrs:
        return all(
            isinstance(value := getattr(settings, attr, ""), str) and value.strip()
            for attr in configuration_attrs
        )
    return descriptor.static_credential is not None


def _validate_allowed_helpers(
    registry: ApprovedHelperRegistry,
    allowed_helper_ids: frozenset[str],
) -> None:
    for helper_id in sorted(allowed_helper_ids):
        try:
            registry.resolve(helper_id)
        except KeyError as error:
            raise ValueError(
                f"session policy references unregistered helper: {helper_id}"
            ) from error


__all__ = [
    "SessionExecutionPolicy",
    "build_session_execution_policy",
    "build_session_execution_policy_for_settings",
    "parse_allowed_helper_ids",
]
