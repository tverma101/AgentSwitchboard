"""Visibility rules for provider-discovered model catalogs."""

from collections.abc import Iterable
from typing import Any

from .model_catalog import (
    ModelCatalogMode,
    ModelCatalogPolicy,
    parse_model_catalog_allowlist,
)
from .settings import Settings

NVIDIA_NIM_PROVIDER_ID = "nvidia_nim"
NVIDIA_NIM_MODEL_PREFIX = f"{NVIDIA_NIM_PROVIDER_ID}/"


def parse_nvidia_nim_model_allowlist(value: str) -> frozenset[str]:
    """Return normalized NVIDIA NIM model ids from a comma/newline list."""
    entries = value.replace("\r", "\n").replace("\n", ",").split(",")
    normalized: set[str] = set()
    for entry in entries:
        model_id = entry.strip()
        if not model_id:
            continue
        normalized.add(model_id.removeprefix(NVIDIA_NIM_MODEL_PREFIX))
    return frozenset(normalized)


def model_catalog_policy_for_settings(
    settings: Settings,
) -> ModelCatalogPolicy | None:
    """Return the generic policy, or ``None`` for legacy compatibility mode.

    The generic settings take precedence whenever either generic setting is
    configured.  With both left empty, the historical NIM-only allowlist
    behavior remains active and all non-NIM providers stay visible.
    """

    mode_value = getattr(settings, "model_catalog_mode", None)
    allowlist_value = getattr(settings, "model_catalog_allowlist", "")
    if not isinstance(allowlist_value, str):
        allowlist_value = ""
    if isinstance(mode_value, str) and not mode_value.strip():
        mode_value = None
    if mode_value is None and not allowlist_value.strip():
        return None

    mode = ModelCatalogMode(mode_value or ModelCatalogMode.CURATED)
    return ModelCatalogPolicy(
        mode=mode,
        allowlist=parse_model_catalog_allowlist(allowlist_value),
    )


def is_discovered_model_visible(
    settings: Settings, provider_id: str, model_id: str
) -> bool:
    """Return whether one discovered model should be exposed to clients."""
    policy = model_catalog_policy_for_settings(settings)
    if policy is not None:
        return policy.is_visible(provider_id, model_id)

    if provider_id != NVIDIA_NIM_PROVIDER_ID:
        return True

    allowlist = parse_nvidia_nim_model_allowlist(
        getattr(settings, "nvidia_nim_model_allowlist", "")
    )
    if "*" in allowlist:
        return True
    return model_id.removeprefix(NVIDIA_NIM_MODEL_PREFIX) in allowlist


def filter_discovered_model_infos(
    settings: Settings,
    provider_id: str,
    model_infos: Iterable[Any],
) -> frozenset[Any]:
    """Filter a provider response before it enters the shared model cache."""
    return frozenset(
        info
        for info in model_infos
        if is_discovered_model_visible(settings, provider_id, info.model_id)
    )


def filter_cached_model_infos(
    settings: Settings, model_infos: Iterable[Any]
) -> tuple[Any, ...]:
    """Filter cached prefixed model refs, including stale entries after config edits."""
    return tuple(
        info
        for info in model_infos
        if "/" not in info.model_id
        or is_discovered_model_visible(
            settings, info.model_id.split("/", 1)[0], info.model_id
        )
    )
