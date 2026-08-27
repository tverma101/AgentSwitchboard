"""Validated, launch-scoped configuration for custom OpenAI endpoints."""

import ipaddress
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

from .provider_catalog import (
    PROVIDER_CATALOG,
    SUPPORTED_PROVIDER_IDS,
    ProviderDescriptor,
)

CUSTOM_PROVIDERS_ENV = "CUSTOM_PROVIDERS_JSON"
MAX_CUSTOM_PROVIDERS = 8
MAX_CUSTOM_PROVIDER_ID_LENGTH = 40
MAX_CUSTOM_PROVIDER_NAME_LENGTH = 120
MAX_CUSTOM_MODEL_ID_LENGTH = 240
MAX_CUSTOM_MODELS = 128
MAX_CUSTOM_CONFIG_BYTES = 128 * 1024

_CUSTOM_PROVIDER_KEYS = frozenset(
    {
        "id",
        "display_name",
        "base_url",
        "api_key",
        "proxy",
        "local",
        "models",
        "enabled",
    }
)
_PROVIDER_ID_RE = re.compile(r"[^a-z0-9]+")
_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})


class SettingsWithCustomProviders(Protocol):
    """Minimum settings surface needed to build a provider registry."""

    custom_providers_json: str


@dataclass(frozen=True, slots=True)
class CustomProviderDescriptor:
    """One user-defined OpenAI-compatible endpoint.

    Credentials and proxy values are intentionally excluded from the repr and
    public serialization. They stay inside the launch-owned descriptor only.
    """

    provider_id: str
    display_name: str
    base_url: str
    api_key: str = field(default="", repr=False)
    proxy: str = field(default="", repr=False)
    local: bool = False
    model_ids: tuple[str, ...] = ()
    enabled: bool = True

    def as_provider_descriptor(self) -> ProviderDescriptor:
        """Adapt this descriptor to the existing provider construction contract."""
        return ProviderDescriptor(
            provider_id=self.provider_id,
            display_name=self.display_name,
            local=self.local,
            static_credential=self.api_key,
            static_proxy=self.proxy,
            default_base_url=self.base_url,
        )

    def public_dict(self) -> dict[str, Any]:
        """Return Admin-safe metadata without a secret or proxy credential."""
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "local": self.local,
            "enabled": self.enabled,
            "api_key_configured": bool(self.api_key),
            "proxy_configured": bool(self.proxy),
            "model_ids": list(self.model_ids),
        }


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    """Frozen built-in plus enabled custom provider catalog for one session."""

    catalog: Mapping[str, ProviderDescriptor]
    custom: Mapping[str, CustomProviderDescriptor]
    order: tuple[str, ...]


def sanitize_provider_id(value: Any) -> str:
    """Normalize a user-facing provider id into a stable safe identifier."""
    if not isinstance(value, str):
        raise ValueError("Custom provider id must be a string")
    normalized = unicodedata.normalize("NFKC", value).encode("ascii", "ignore").decode()
    provider_id = _PROVIDER_ID_RE.sub("_", normalized.casefold()).strip("_")
    if provider_id and provider_id[0].isdigit():
        provider_id = f"custom_{provider_id}"
    if not provider_id:
        raise ValueError("Custom provider id must contain a letter or number")
    if len(provider_id) > MAX_CUSTOM_PROVIDER_ID_LENGTH:
        raise ValueError(
            f"Custom provider id must be at most {MAX_CUSTOM_PROVIDER_ID_LENGTH} characters"
        )
    return provider_id


def parse_custom_provider_json(
    raw: str,
    *,
    built_in_provider_ids: Iterable[str] = SUPPORTED_PROVIDER_IDS,
) -> tuple[CustomProviderDescriptor, ...]:
    """Parse and validate the complete managed custom-provider document."""
    if not isinstance(raw, str):
        raise ValueError(f"{CUSTOM_PROVIDERS_ENV} must be a JSON string")
    if len(raw.encode("utf-8")) > MAX_CUSTOM_CONFIG_BYTES:
        raise ValueError(f"{CUSTOM_PROVIDERS_ENV} is too large")
    if not raw.strip():
        return ()
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{CUSTOM_PROVIDERS_ENV} is not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(document, dict) or set(document) != {"providers"}:
        raise ValueError(f"{CUSTOM_PROVIDERS_ENV} must contain only a providers array")
    entries = document["providers"]
    if not isinstance(entries, list):
        raise ValueError(f"{CUSTOM_PROVIDERS_ENV}.providers must be an array")
    if len(entries) > MAX_CUSTOM_PROVIDERS:
        raise ValueError(f"At most {MAX_CUSTOM_PROVIDERS} custom providers are allowed")

    built_ins = frozenset(built_in_provider_ids)
    descriptors: list[CustomProviderDescriptor] = []
    seen_ids: set[str] = set()
    for entry in entries:
        descriptor = _parse_custom_provider_entry(entry, built_ins)
        if descriptor.provider_id in seen_ids:
            raise ValueError(f"Duplicate custom provider id: {descriptor.provider_id}")
        seen_ids.add(descriptor.provider_id)
        descriptors.append(descriptor)
    return tuple(descriptors)


def serialize_custom_providers(
    providers: Iterable[CustomProviderDescriptor],
) -> str:
    """Serialize descriptors deterministically for managed persistence."""
    entries = [
        {
            "id": provider.provider_id,
            "display_name": provider.display_name,
            "base_url": provider.base_url,
            "api_key": provider.api_key,
            "proxy": provider.proxy,
            "local": provider.local,
            "models": list(provider.model_ids),
            "enabled": provider.enabled,
        }
        for provider in sorted(providers, key=lambda item: item.provider_id)
    ]
    return json.dumps({"providers": entries}, ensure_ascii=True, separators=(",", ":"))


def provider_registry_from_json(raw: str) -> ProviderRegistry:
    """Compose a frozen catalog without mutating the built-in catalog."""
    custom_descriptors = parse_custom_provider_json(raw)
    enabled_custom = tuple(
        sorted(
            (descriptor for descriptor in custom_descriptors if descriptor.enabled),
            key=lambda item: item.provider_id,
        )
    )
    custom = {descriptor.provider_id: descriptor for descriptor in enabled_custom}
    catalog = dict(PROVIDER_CATALOG)
    catalog.update(
        {
            provider_id: descriptor.as_provider_descriptor()
            for provider_id, descriptor in custom.items()
        }
    )
    return ProviderRegistry(
        catalog=MappingProxyType(catalog),
        custom=MappingProxyType(custom),
        order=tuple(catalog),
    )


def provider_registry_for_settings(
    settings: SettingsWithCustomProviders,
) -> ProviderRegistry:
    """Build the registry for one immutable Settings snapshot."""
    raw = getattr(settings, "custom_providers_json", "")
    return provider_registry_from_json(raw if isinstance(raw, str) else "")


def public_custom_provider_status(raw: str) -> list[dict[str, Any]]:
    """Return stable, secret-free status rows for the Admin surface."""
    return [descriptor.public_dict() for descriptor in parse_custom_provider_json(raw)]


def update_custom_provider_json(
    raw: str,
    values: Mapping[str, Any],
    *,
    existing_provider_id: str | None = None,
) -> str:
    """Validate one add/edit payload and return the new managed document."""
    current = list(parse_custom_provider_json(raw))
    normalized_existing = (
        sanitize_provider_id(existing_provider_id)
        if existing_provider_id is not None
        else None
    )
    provider_id = sanitize_provider_id(
        values.get("id", normalized_existing)
        if normalized_existing is None
        else normalized_existing
    )
    old = next((item for item in current if item.provider_id == provider_id), None)
    if normalized_existing is not None and old is None:
        raise ValueError(f"Unknown custom provider: {provider_id}")

    def value(name: str, default: Any = None) -> Any:
        return values.get(name, default)

    display_name = value("display_name", old.display_name if old else "")
    base_url = value("base_url", old.base_url if old else "")
    api_key = value("api_key", None)
    if api_key is None:
        api_key = old.api_key if old else ""
    proxy = value("proxy", old.proxy if old else "")
    descriptor_values = {
        "id": provider_id,
        "display_name": display_name,
        "base_url": base_url,
        "api_key": api_key,
        "proxy": proxy,
        "local": value("local", old.local if old else False),
        "models": value("models", list(old.model_ids) if old else []),
        "enabled": value("enabled", old.enabled if old else True),
    }
    descriptor = _parse_custom_provider_entry(
        descriptor_values,
        frozenset(SUPPORTED_PROVIDER_IDS),
    )
    if old is None and any(
        item.provider_id == descriptor.provider_id for item in current
    ):
        raise ValueError(f"Duplicate custom provider id: {descriptor.provider_id}")
    if old is not None:
        current = [item for item in current if item.provider_id != old.provider_id]
    current.append(descriptor)
    return serialize_custom_providers(current)


def remove_custom_provider_json(raw: str, provider_id: str) -> str:
    """Remove one configured custom provider and preserve all others."""
    normalized_id = sanitize_provider_id(provider_id)
    current = list(parse_custom_provider_json(raw))
    if not any(item.provider_id == normalized_id for item in current):
        raise ValueError(f"Unknown custom provider: {normalized_id}")
    return serialize_custom_providers(
        item for item in current if item.provider_id != normalized_id
    )


def _parse_custom_provider_entry(
    entry: Any,
    built_in_provider_ids: frozenset[str],
) -> CustomProviderDescriptor:
    if not isinstance(entry, dict):
        raise ValueError("Each custom provider must be an object")
    unknown_keys = set(entry) - _CUSTOM_PROVIDER_KEYS
    if unknown_keys:
        raise ValueError(
            "Unsupported custom provider fields: "
            + ", ".join(sorted(str(key) for key in unknown_keys))
        )

    provider_id = sanitize_provider_id(entry.get("id"))
    if provider_id in built_in_provider_ids:
        raise ValueError(
            f"Custom provider id collides with built-in provider: {provider_id}"
        )
    display_name = entry.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError(f"Custom provider {provider_id} needs a display_name")
    display_name = display_name.strip()
    if len(display_name) > MAX_CUSTOM_PROVIDER_NAME_LENGTH:
        raise ValueError(f"Custom provider {provider_id} display_name is too long")

    base_url = _validated_base_url(provider_id, entry.get("base_url"))
    api_key = _string_value(entry.get("api_key", ""), "api_key")
    proxy = _validated_proxy(provider_id, entry.get("proxy", ""))
    local = entry.get("local", False)
    if not isinstance(local, bool):
        raise ValueError(f"Custom provider {provider_id} local must be a boolean")
    endpoint_is_local = _is_local_endpoint(base_url)
    if endpoint_is_local != local:
        classification = "local" if endpoint_is_local else "remote"
        raise ValueError(
            f"Custom provider {provider_id} must set local={endpoint_is_local!r} "
            f"for its {classification} endpoint"
        )
    if not local and not api_key.strip():
        raise ValueError(f"Custom provider {provider_id} requires an API key")

    models = entry.get("models", [])
    if not isinstance(models, list) or any(
        not isinstance(model, str) for model in models
    ):
        raise ValueError(f"Custom provider {provider_id} models must be a string array")
    model_ids: list[str] = []
    for model in models:
        model_id = model.strip()
        if not model_id:
            continue
        if len(model_id) > MAX_CUSTOM_MODEL_ID_LENGTH:
            raise ValueError(f"Custom provider {provider_id} model id is too long")
        if model_id not in model_ids:
            model_ids.append(model_id)
    if len(model_ids) > MAX_CUSTOM_MODELS:
        raise ValueError(
            f"Custom provider {provider_id} has too many explicit model ids"
        )
    enabled = entry.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"Custom provider {provider_id} enabled must be a boolean")
    return CustomProviderDescriptor(
        provider_id=provider_id,
        display_name=display_name,
        base_url=base_url,
        api_key=api_key,
        proxy=proxy,
        local=local,
        model_ids=tuple(model_ids),
        enabled=enabled,
    )


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Custom provider {field_name} must be a string")
    return value.strip()


def _validated_base_url(provider_id: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Custom provider {provider_id} needs a base_url")
    parsed = _split_url(provider_id, value, field_name="base_url")
    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise ValueError(
            f"Custom provider {provider_id} base_url must use HTTPS unless it is loopback HTTP"
        )
    return urlunsplit(parsed).rstrip("/")


def _validated_proxy(provider_id: str, value: Any) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError(f"Custom provider {provider_id} proxy must be a string")
    parsed = _split_url(provider_id, value, field_name="proxy")
    if parsed.scheme not in _PROXY_SCHEMES:
        raise ValueError(
            f"Custom provider {provider_id} proxy must use http, https, socks5, or socks5h"
        )
    return urlunsplit(parsed)


def _split_url(provider_id: str, value: str, *, field_name: str) -> SplitResult:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            f"Custom provider {provider_id} {field_name} is malformed"
        ) from exc
    if parsed.scheme not in {"http", "https"} and field_name == "base_url":
        raise ValueError(
            f"Custom provider {provider_id} base_url must use http or https"
        )
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            f"Custom provider {provider_id} {field_name} must not contain URL credentials"
        )
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(
            f"Custom provider {provider_id} {field_name} has an invalid port"
        )
    if parsed.query or parsed.fragment:
        raise ValueError(
            f"Custom provider {provider_id} {field_name} must not contain query or fragment"
        )
    return parsed


def _is_local_endpoint(url: str) -> bool:
    host = urlsplit(url).hostname
    return _is_loopback_host(host) or _is_private_ip(host)


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip("[]").casefold()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_private_ip(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host.strip("[]")).is_private
    except ValueError:
        return False
