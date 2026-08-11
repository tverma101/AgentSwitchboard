"""Human-friendly model labels that never replace routable model ids."""

import re

from .provider_catalog import PROVIDER_CATALOG

_KNOWN_LABELS = {
    "deepseek-chat": "DeepSeek Chat",
    "deepseek-reasoner": "DeepSeek Reasoner",
    "deepseek-v4-flash-free": "DeepSeek V4 Flash Free",
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "glm-5": "GLM 5",
    "glm-5.2": "GLM 5.2",
    "glm-5.1": "GLM 5.1",
}


def model_display_name(model_ref: str) -> str:
    """Return a readable label while preserving ``model_ref`` for routing."""
    display_ref = model_ref.removeprefix("anthropic/")
    provider_id, separator, model_id = display_ref.partition("/")
    if not separator:
        return _pretty_model_id(model_ref)
    provider = PROVIDER_CATALOG.get(provider_id)
    provider_label = provider.display_name if provider is not None else provider_id
    return f"{provider_label} · {_pretty_model_id(model_id)}"


def model_display_names(
    model_refs: list[str] | tuple[str, ...] | set[str],
) -> dict[str, str]:
    """Return labels keyed by the exact model ids used in config and requests."""
    return {model_ref: model_display_name(model_ref) for model_ref in model_refs}


def _pretty_model_id(model_id: str) -> str:
    if model_id in _KNOWN_LABELS:
        return _KNOWN_LABELS[model_id]
    leaf = model_id.rsplit("/", 1)[-1]
    if leaf in _KNOWN_LABELS:
        return _KNOWN_LABELS[leaf]
    words = re.sub(r"[-_:]+", " ", leaf).split()
    return " ".join(
        word.upper() if word.isupper() else word.capitalize() for word in words
    )
