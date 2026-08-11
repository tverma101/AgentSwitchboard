"""Visibility rules for provider-discovered model catalogs."""

from collections.abc import Iterable
from typing import Any

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


def is_discovered_model_visible(
    settings: Settings, provider_id: str, model_id: str
) -> bool:
    """Return whether one discovered model should be exposed to clients."""
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
