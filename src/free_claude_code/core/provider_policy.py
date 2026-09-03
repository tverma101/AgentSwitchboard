"""Immutable session policy and pre-network provider egress guard."""

from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse

from free_claude_code.core.trace import trace_event


class ProviderPolicyError(PermissionError):
    """Raised before a provider or helper request is allowed to start."""


class ProviderPolicyMode(StrEnum):
    STRICT = "strict"
    ALLOW_LISTED = "allow-listed"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    """Launch-time provider/tool permissions; never inferred from capabilities."""

    primary_provider: str
    primary_model: str
    allowed_helpers: frozenset[str] = frozenset()
    allowed_local_tools: frozenset[str] = frozenset({"computer", "browser"})
    forbidden_provider_families: frozenset[str] = frozenset(
        {"anthropic", "openai", "codex", "chatgpt"}
    )
    mode: ProviderPolicyMode = ProviderPolicyMode.STRICT
    paid_fallback: bool = False
    # Model-list discovery is read-only catalog metadata, but it still uses a
    # provider credential. The session builder fills this with the providers
    # explicitly configured for the current generation; it must not become a
    # wildcard permission for inference traffic.
    discovery_provider_families: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.primary_provider or not self.primary_model:
            raise ValueError("primary provider and model are required")
        if self.mode is ProviderPolicyMode.STRICT and self.paid_fallback:
            raise ValueError("strict policy cannot permit paid fallback")


@dataclass(slots=True)
class ProviderEgressGuard:
    """Authorize provider destinations before any HTTP client is invoked."""

    policy: ProviderPolicy
    _counts: dict[str, int] = field(default_factory=dict)
    _blocked_counts: dict[str, int] = field(default_factory=dict)

    def authorize(
        self,
        provider_family: str,
        *,
        category: str = "model",
        destination_host: str | None = None,
    ) -> bool:
        family = provider_family.strip().lower()
        allowed = family == self.policy.primary_provider.lower()
        if category == "model_discovery":
            allowed = allowed or family in {
                provider.lower() for provider in self.policy.discovery_provider_families
            }
        elif category == "local_tool":
            allowed = family == "local" or family in {
                tool.lower() for tool in self.policy.allowed_local_tools
            }
        elif self.policy.mode is ProviderPolicyMode.ALLOW_LISTED:
            allowed = allowed or family in {
                helper.lower() for helper in self.policy.allowed_helpers
            }
        # Discovery is an explicitly configured, read-only metadata request.
        # It may inspect a connected account such as OpenAI without granting
        # that provider inference egress; the normal model category remains
        # fail-closed against the forbidden-family set.
        if category != "model_discovery" and family in {
            item.lower() for item in self.policy.forbidden_provider_families
        }:
            allowed = False
        decision = "allowed" if allowed else "blocked"
        if not allowed and self.policy.mode is ProviderPolicyMode.DIAGNOSTIC:
            decision = "diagnostic_blocked"
        trace_event(
            stage="provider_policy",
            event="provider.egress.decision",
            source="provider_policy",
            provider_family=family,
            destination_host=destination_host,
            category=category,
            decision=decision,
            policy_mode=self.policy.mode.value,
            primary_provider=self.policy.primary_provider,
            paid_fallback=self.policy.paid_fallback,
        )
        if not allowed:
            receipt_family = "local" if category == "local_tool" else family
            self._blocked_counts[receipt_family] = (
                self._blocked_counts.get(receipt_family, 0) + 1
            )
            if self.policy.mode is ProviderPolicyMode.DIAGNOSTIC:
                return False
            raise ProviderPolicyError(
                f"provider egress blocked before network I/O: {provider_family} ({category})"
            )
        receipt_family = "local" if category == "local_tool" else family
        self._counts[receipt_family] = self._counts.get(receipt_family, 0) + 1
        return True

    def authorize_url(
        self,
        url: str,
        *,
        category: str = "model",
        provider_family: str | None = None,
    ) -> bool:
        """Reject malformed URLs before a transport is constructed."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ProviderPolicyError(
                "provider egress URL must use http(s) and include a host"
            )
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            if category not in {"local_tool", "model_discovery"} and (
                provider_family is None
                or provider_family.strip().lower()
                != self.policy.primary_provider.lower()
            ):
                raise ProviderPolicyError("local URL is only valid for local tools")
            if category == "model_discovery":
                if provider_family is None:
                    raise ProviderPolicyError(
                        "local model discovery requires a provider family"
                    )
                return self.authorize(
                    provider_family,
                    category=category,
                    destination_host=parsed.hostname,
                )
            if category != "local_tool":
                return self.authorize(
                    provider_family or self.policy.primary_provider,
                    category=category,
                    destination_host=parsed.hostname,
                )
            return self.authorize(
                "local",
                category="local_tool",
                destination_host=parsed.hostname,
            )
        return self.authorize(
            provider_family or parsed.hostname,
            category=category,
            destination_host=parsed.hostname,
        )

    def receipt(self) -> dict[str, object]:
        return {
            "primary_provider": self.policy.primary_provider,
            "primary_model": self.policy.primary_model,
            "mode": self.policy.mode.value,
            "paid_fallback": self.policy.paid_fallback,
            "counts": dict(sorted(self._counts.items())),
            "blocked_counts": dict(sorted(self._blocked_counts.items())),
        }
