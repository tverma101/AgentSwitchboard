"""Immutable provider policy and metadata-only pre-network egress accounting."""

import hashlib
import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from urllib.parse import urlparse

from free_claude_code.core.trace import trace_event

DEFAULT_FORBIDDEN_PROVIDER_FAMILIES = frozenset(
    {"anthropic", "openai", "codex", "chatgpt"}
)
_EGRESS_CATEGORIES = frozenset({"model", "helper", "local_tool"})
_LOCAL_TOOL_FAMILIES = frozenset({"local", "computer", "browser"})
_USAGE_FIELDS = (
    "request_count",
    "model_requests",
    "helper_requests",
    "local_tool_actions",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "image_bytes",
    "retry_count",
)
_PROVIDER_HOST_FAMILIES = {
    "api.anthropic.com": "anthropic",
    "api.openai.com": "openai",
    "chat.openai.com": "chatgpt",
    "chatgpt.com": "chatgpt",
}


class ProviderPolicyError(PermissionError):
    """Raised before a provider or helper request is allowed to start."""

    policy_blocked = True


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
    forbidden_provider_families: frozenset[str] = DEFAULT_FORBIDDEN_PROVIDER_FAMILIES
    mode: ProviderPolicyMode = ProviderPolicyMode.STRICT
    paid_fallback: bool = False
    session_id: str | None = None

    def __post_init__(self) -> None:
        primary_provider = _provider_family(self.primary_provider)
        primary_model = _model_label(self.primary_model, field_name="primary_model")
        mode = _policy_mode(self.mode)
        allowed_helpers = frozenset(
            _helper_ref(value) for value in _string_values(self.allowed_helpers)
        )
        allowed_local_tools = frozenset(
            _provider_family(value)
            for value in _string_values(self.allowed_local_tools)
        )
        forbidden = frozenset(
            _provider_family(value)
            for value in _string_values(self.forbidden_provider_families)
        )
        session_id = _optional_label(self.session_id)

        if not primary_provider or not primary_model:
            raise ValueError("primary provider and model are required")
        if primary_provider in forbidden:
            raise ValueError(
                f"primary provider {primary_provider!r} is forbidden by policy"
            )
        if mode is ProviderPolicyMode.STRICT and self.paid_fallback:
            raise ValueError("strict policy cannot permit paid fallback")
        if not isinstance(self.paid_fallback, bool):
            raise TypeError("paid_fallback must be a bool")

        object.__setattr__(self, "primary_provider", primary_provider)
        object.__setattr__(self, "primary_model", primary_model)
        object.__setattr__(self, "allowed_helpers", allowed_helpers)
        object.__setattr__(self, "allowed_local_tools", allowed_local_tools)
        object.__setattr__(self, "forbidden_provider_families", forbidden)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "session_id", session_id)

    @classmethod
    def from_settings(
        cls,
        settings: object,
        *,
        primary_provider: str | None = None,
        primary_model: str | None = None,
        session_id: str | None = None,
    ) -> ProviderPolicy:
        """Resolve one immutable policy from launch settings and safe overrides."""

        configured_ref = _setting_string(settings, "model")
        configured_provider, configured_model = _split_model_ref(configured_ref)
        return cls(
            primary_provider=primary_provider or configured_provider,
            primary_model=primary_model or configured_model,
            allowed_helpers=frozenset(
                _csv_setting(settings, "provider_policy_allowed_helpers")
            ),
            allowed_local_tools=frozenset(
                _csv_setting(
                    settings,
                    "provider_policy_allowed_local_tools",
                    default=("computer", "browser"),
                )
            ),
            mode=_setting_mode(settings, "provider_policy_mode"),
            paid_fallback=_setting_bool(settings, "provider_policy_paid_fallback"),
            session_id=session_id,
        )

    def allows(
        self,
        provider_family: str,
        *,
        model: str | None = None,
        category: str = "model",
    ) -> bool:
        """Return whether this exact provider/tool route is permitted."""

        return (
            self.denial_reason(
                provider_family,
                model=model,
                category=category,
            )
            is None
        )

    def denial_reason(
        self,
        provider_family: str,
        *,
        model: str | None = None,
        category: str = "model",
    ) -> str | None:
        """Return a stable reason when a route is not permitted."""

        if category not in _EGRESS_CATEGORIES:
            raise ValueError(
                f"unknown provider egress category {category!r}; "
                f"expected one of {sorted(_EGRESS_CATEGORIES)}"
            )
        family = _provider_family(provider_family)
        model_label = _optional_label(model)
        if family in self.forbidden_provider_families:
            return "forbidden_provider_family"

        if category == "local_tool":
            if family not in _LOCAL_TOOL_FAMILIES:
                return "non_local_tool_provider"
            if model_label is None:
                return None
            tool_family = model_label.split(".", 1)[0].casefold()
            if tool_family not in self.allowed_local_tools:
                return "local_tool_not_allowlisted"
            return None

        if family == self.primary_provider:
            if model_label is None or _same_model(model_label, self.primary_model):
                return None
            return "primary_model_not_selected"

        if category == "helper" and self.mode is ProviderPolicyMode.ALLOW_LISTED:
            if _helper_is_allowlisted(
                self.allowed_helpers,
                family,
                model_label,
            ):
                return None
            return "helper_not_allowlisted"

        return "provider_not_selected"

    def preview_receipt(self) -> dict[str, object]:
        """Return a compact zero-network launch diagnostic."""

        forbidden = sorted(self.forbidden_provider_families)
        return {
            "primary_provider": self.primary_provider,
            "primary_model": self.primary_model,
            "mode": self.mode.value,
            "paid_fallback": self.paid_fallback,
            "allowed_helpers": sorted(self.allowed_helpers),
            "allowed_local_tools": sorted(self.allowed_local_tools),
            "forbidden_provider_families": forbidden,
            "fallback_decision": "blocked",
            "fallback_provider_families": forbidden,
            "would_be_fallback": forbidden,
            "network": "none",
        }

    def as_receipt(self) -> dict[str, object]:
        """Return policy metadata without exposing a raw session identifier."""

        return {
            "session_id": _session_key(self.session_id),
            "primary_provider": self.primary_provider,
            "primary_model": self.primary_model,
            "mode": self.mode.value,
            "paid_fallback": self.paid_fallback,
            "allowed_helpers": sorted(self.allowed_helpers),
            "allowed_local_tools": sorted(self.allowed_local_tools),
            "forbidden_provider_families": sorted(self.forbidden_provider_families),
        }


SessionProviderPolicy = ProviderPolicy


@dataclass(slots=True)
class ProviderEgressGuard:
    """Authorize destinations before I/O and retain sanitized session totals."""

    policy: ProviderPolicy
    _counts: dict[str, int] = field(default_factory=dict)
    _blocked_counts: dict[str, int] = field(default_factory=dict)
    _session_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    _session_blocked_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    _session_usage: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    _session_would_be_fallbacks: dict[str, dict[str, int]] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def check(
        self,
        provider_family: str,
        *,
        model: str | None = None,
        category: str = "model",
        destination_host: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> bool:
        """Check a route before provider construction without counting I/O."""

        return self._decide(
            provider_family,
            model=model,
            category=category,
            destination_host=destination_host,
            session_id=session_id,
            request_id=request_id,
            count_request=False,
        )

    def authorize(
        self,
        provider_family: str,
        *,
        model: str | None = None,
        category: str = "model",
        destination_host: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> bool:
        """Authorize one outbound attempt before its transport is called."""

        return self._decide(
            provider_family,
            model=model,
            category=category,
            destination_host=destination_host,
            session_id=session_id,
            request_id=request_id,
            count_request=True,
        )

    def authorize_url(
        self,
        url: str,
        *,
        model: str | None = None,
        category: str = "model",
        provider_family: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> bool:
        """Reject malformed or forbidden URLs before a transport is constructed."""

        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ProviderPolicyError(
                "provider egress URL must use http(s), include a host, "
                "and not embed credentials"
            )
        host = parsed.hostname.casefold()
        if category == "local_tool":
            if not _is_loopback_host(host):
                return self._decide(
                    host,
                    model=model,
                    category=category,
                    destination_host=host,
                    session_id=session_id,
                    request_id=request_id,
                    count_request=True,
                )
            return self.authorize(
                "local",
                model=model,
                category=category,
                destination_host=host,
                session_id=session_id,
                request_id=request_id,
            )

        family = _PROVIDER_HOST_FAMILIES.get(host) or provider_family or host
        if _is_loopback_host(host) and (
            provider_family is None
            or _provider_family(provider_family) != self.policy.primary_provider
        ):
            raise ProviderPolicyError(
                "local URL is only valid for the selected provider"
            )
        return self.authorize(
            family,
            model=model,
            category=category,
            destination_host=host,
            session_id=session_id,
            request_id=request_id,
        )

    def record_usage(
        self,
        provider_family: str,
        *,
        model: str | None = None,
        category: str = "model",
        session_id: str | None = None,
        request_id: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        image_bytes: int = 0,
        retry_count: int = 0,
    ) -> None:
        """Add sanitized numeric usage to one session's accounting bucket."""

        if category not in _EGRESS_CATEGORIES:
            raise ValueError(f"unknown provider egress category: {category}")
        family = _accounting_family(provider_family, category)
        session = _session_key(session_id or self.policy.session_id)
        values = {
            "input_tokens": _non_negative_int(input_tokens),
            "output_tokens": _non_negative_int(output_tokens),
            "cache_read_tokens": _non_negative_int(cache_read_tokens),
            "cache_write_tokens": _non_negative_int(cache_write_tokens),
            "image_bytes": _non_negative_int(image_bytes),
            "retry_count": _non_negative_int(retry_count),
        }
        with self._lock:
            totals = self._usage_bucket(session, family)
            for key, value in values.items():
                totals[key] += value
        trace_event(
            stage="provider_policy",
            event="provider.egress.usage",
            source="provider_policy",
            session_id=session,
            request_id=_safe_identifier(request_id),
            provider_family=family,
            model=_safe_identifier(model),
            category=category,
            input_tokens=values["input_tokens"],
            output_tokens=values["output_tokens"],
            cache_read_tokens=values["cache_read_tokens"],
            cache_write_tokens=values["cache_write_tokens"],
            image_bytes=values["image_bytes"],
            retry_count=values["retry_count"],
        )

    def receipt(self, session_id: str | None = None) -> dict[str, object]:
        """Return aggregate or one-session metadata-only usage receipt."""

        selected_session = (
            _session_key(session_id or self.policy.session_id)
            if session_id is not None or self.policy.session_id is not None
            else None
        )
        with self._lock:
            if selected_session is None:
                counts = dict(self._counts)
                blocked_counts = dict(self._blocked_counts)
                usage = _merge_usage(self._session_usage)
                would_be = _merge_counts(self._session_would_be_fallbacks)
                sessions = {
                    key: self._session_receipt_data(key)
                    for key in sorted(self._session_usage)
                }
                for key in sorted(self._session_counts):
                    sessions.setdefault(key, self._session_receipt_data(key))
            else:
                counts = dict(self._session_counts.get(selected_session, {}))
                blocked_counts = dict(
                    self._session_blocked_counts.get(selected_session, {})
                )
                usage = _copy_usage(self._session_usage.get(selected_session, {}))
                would_be = dict(
                    self._session_would_be_fallbacks.get(selected_session, {})
                )
                sessions = {}

        payload: dict[str, object] = {
            **self.policy.as_receipt(),
            "session_id": selected_session or "all",
            "counts": dict(sorted(counts.items())),
            "blocked_counts": dict(sorted(blocked_counts.items())),
            "would_be_fallbacks": dict(sorted(would_be.items())),
            "accounting": _render_usage(usage, self.policy),
        }
        if sessions:
            payload["sessions"] = sessions
        return payload

    def session_receipt(self, session_id: str) -> dict[str, object]:
        """Return one sanitized receipt keyed to a caller-provided session."""

        return self.receipt(session_id)

    def _decide(
        self,
        provider_family: str,
        *,
        model: str | None,
        category: str,
        destination_host: str | None,
        session_id: str | None,
        request_id: str | None,
        count_request: bool,
    ) -> bool:
        family = _provider_family(provider_family)
        reason = self.policy.denial_reason(
            family,
            model=model,
            category=category,
        )
        session = _session_key(session_id or self.policy.session_id)
        allowed = reason is None
        decision = "allowed" if allowed else "blocked"
        if not allowed and self.policy.mode is ProviderPolicyMode.DIAGNOSTIC:
            decision = "would_be_fallback"
        trace_event(
            stage="provider_policy",
            event="provider.egress.decision",
            source="provider_policy",
            session_id=session,
            request_id=_safe_identifier(request_id),
            provider_family=family,
            model=_safe_identifier(model),
            destination_host=_safe_host(destination_host),
            category=category,
            decision=decision,
            reason=reason,
            policy_mode=self.policy.mode.value,
            primary_provider=self.policy.primary_provider,
            primary_model=self.policy.primary_model,
            paid_fallback=self.policy.paid_fallback,
            fault_domain=("harness_bridge" if not allowed else None),
            confidence=("high" if not allowed else None),
            evidence_codes=["provider_policy_blocked"] if not allowed else [],
        )
        if not allowed:
            with self._lock:
                blocked_family = _accounting_family(family, category)
                self._blocked_counts[blocked_family] = (
                    self._blocked_counts.get(blocked_family, 0) + 1
                )
                session_blocked = self._session_blocked_counts.setdefault(session, {})
                session_blocked[blocked_family] = (
                    session_blocked.get(blocked_family, 0) + 1
                )
                if category in {"model", "helper"}:
                    would_be = self._session_would_be_fallbacks.setdefault(session, {})
                    would_be[family] = would_be.get(family, 0) + 1
            if self.policy.mode is ProviderPolicyMode.DIAGNOSTIC:
                return False
            raise ProviderPolicyError(
                f"provider egress blocked before network I/O: "
                f"{provider_family} ({category})"
            )

        if count_request:
            with self._lock:
                counted_family = _accounting_family(family, category)
                self._counts[counted_family] = self._counts.get(counted_family, 0) + 1
                session_counts = self._session_counts.setdefault(session, {})
                session_counts[counted_family] = (
                    session_counts.get(counted_family, 0) + 1
                )
                usage = self._usage_bucket(session, counted_family)
                usage["request_count"] += 1
                if category == "model":
                    usage["model_requests"] += 1
                elif category == "helper":
                    usage["helper_requests"] += 1
                else:
                    usage["local_tool_actions"] += 1
        return True

    def _usage_bucket(self, session: str, family: str) -> dict[str, int]:
        per_family = self._session_usage.setdefault(session, {})
        return per_family.setdefault(family, _empty_usage())

    def _session_receipt_data(self, session: str) -> dict[str, object]:
        return {
            "counts": dict(sorted(self._session_counts.get(session, {}).items())),
            "blocked_counts": dict(
                sorted(self._session_blocked_counts.get(session, {}).items())
            ),
            "would_be_fallbacks": dict(
                sorted(self._session_would_be_fallbacks.get(session, {}).items())
            ),
            "accounting": _render_usage(
                self._session_usage.get(session, {}), self.policy
            ),
        }


def _policy_mode(value: object) -> ProviderPolicyMode:
    if isinstance(value, ProviderPolicyMode):
        return value
    if isinstance(value, str):
        return ProviderPolicyMode(value.strip().casefold())
    raise TypeError("mode must be a ProviderPolicyMode or string")


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (frozenset, set, tuple, list)):
        values = tuple(value)
        if not all(isinstance(item, str) for item in values):
            raise TypeError("policy values must be strings")
        return tuple(item for item in values if isinstance(item, str))
    raise TypeError("policy values must be strings or string collections")


def _provider_family(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("provider family must be a string")
    return value.strip().casefold()


def _model_label(value: object, *, field_name: str = "model") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    label = value.strip()
    if not label:
        raise ValueError(f"{field_name} must not be empty")
    return label


def _optional_label(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("session and request identifiers must be strings")
    label = value.strip()
    return label or None


def _helper_ref(value: str) -> str:
    ref = value.strip()
    if not ref:
        raise ValueError("allowed helper references must not be empty")
    provider, separator, model = ref.partition("/")
    if not separator:
        return _provider_family(provider)
    normalized_provider = _provider_family(provider)
    normalized_model = _model_label(model, field_name="helper model")
    return f"{normalized_provider}/{normalized_model}"


def _same_model(left: str, right: str) -> bool:
    return left.casefold() == right.casefold()


def _helper_is_allowlisted(
    allowed_helpers: frozenset[str],
    family: str,
    model: str | None,
) -> bool:
    if family in allowed_helpers:
        return True
    if model is None:
        return False
    exact = f"{family}/{model}"
    wildcard = f"{family}/*"
    return exact in allowed_helpers or wildcard in allowed_helpers


def _split_model_ref(value: str) -> tuple[str, str]:
    provider, separator, model = value.partition("/")
    if not separator or not provider.strip() or not model.strip():
        raise ValueError("MODEL must use the form provider/model")
    return _provider_family(provider), _model_label(model)


def _setting_string(settings: object, name: str) -> str:
    value = getattr(settings, name, "")
    return value.strip() if isinstance(value, str) else ""


def _csv_setting(
    settings: object,
    name: str,
    *,
    default: tuple[str, ...] = (),
) -> tuple[str, ...]:
    value = _setting_string(settings, name)
    if not value:
        return default
    return tuple(
        dict.fromkeys(part.strip() for part in value.split(",") if part.strip())
    )


def _setting_mode(settings: object, name: str) -> ProviderPolicyMode:
    value = getattr(settings, name, ProviderPolicyMode.STRICT)
    if isinstance(value, ProviderPolicyMode):
        return value
    if isinstance(value, str) and value.strip():
        return ProviderPolicyMode(value.strip().casefold())
    return ProviderPolicyMode.STRICT


def _setting_bool(settings: object, name: str) -> bool:
    value = getattr(settings, name, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return False


def _accounting_family(provider_family: str, category: str) -> str:
    return "local" if category == "local_tool" else _provider_family(provider_family)


def _empty_usage() -> dict[str, int]:
    return dict.fromkeys(_USAGE_FIELDS, 0)


def _copy_usage(
    usage: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, int]]:
    return {
        family: {key: int(values.get(key, 0)) for key in _USAGE_FIELDS}
        for family, values in usage.items()
    }


def _merge_usage(
    sessions: Mapping[str, Mapping[str, Mapping[str, int]]],
) -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = {}
    for usage in sessions.values():
        for family, values in usage.items():
            totals = merged.setdefault(family, _empty_usage())
            for key in _USAGE_FIELDS:
                totals[key] += _non_negative_int(values.get(key, 0))
    return merged


def _merge_counts(sessions: Mapping[str, Mapping[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for counts in sessions.values():
        for family, count in counts.items():
            merged[family] = merged.get(family, 0) + _non_negative_int(count)
    return merged


def _render_usage(
    usage: Mapping[str, Mapping[str, int]],
    policy: ProviderPolicy,
) -> dict[str, dict[str, int]]:
    families = set(usage) | {
        "local",
        policy.primary_provider,
        *(_provider_family(ref.partition("/")[0]) for ref in policy.allowed_helpers),
        *policy.forbidden_provider_families,
    }
    return {
        family: {
            key: _non_negative_int(usage.get(family, {}).get(key, 0))
            for key in _USAGE_FIELDS
        }
        for family in sorted(families)
    }


def _non_negative_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return 0


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost", "ip6-localhost"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _session_key(session_id: str | None) -> str:
    if not session_id:
        return "unbound"
    digest = hashlib.sha256(session_id.encode("utf-8", errors="replace")).hexdigest()
    return f"session_{digest[:16]}"


def _safe_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    label = value.strip()
    if not label:
        return None
    if len(label) <= 128 and all(char.isalnum() or char in "._:/-" for char in label):
        return label
    digest = hashlib.sha256(label.encode("utf-8", errors="replace")).hexdigest()
    return f"hash_{digest[:16]}"


def _safe_host(value: str | None) -> str | None:
    if value is None:
        return None
    host = value.strip().casefold()
    return host[:253] if host else None
